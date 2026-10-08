"""Real CPU CLIP, DB vectors, authenticated feed activation and rollback."""

import io
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from test_core_loop_integration import delete_pin_objects, wait_ready
from test_phase3_complete import personalized_config

from app.config import Settings
from app.database import make_engine
from app.feed.contracts import FeedContext
from app.logging.models import EventReceipt, FeedRequest, Impression, ServedFeature, ServedItem
from app.main import create_app
from app.ml.baselines import CatalogCandidateSource
from app.ml.config import EmbeddingConfig, SplitCutoffs, TrainingManifest
from app.ml.contracts import PinContent
from app.ml.data import adapt_interactions, import_catalog, load_interactions, online_inputs
from app.ml.embeddings import ClipPinEmbedder
from app.ml.models import PinEmbedding
from app.ml.retrieval import ExactVectorRetriever, PgvectorANNRetriever
from app.ml.vector_store import catalog_vectors, store_content_embedding
from app.models import ImportedInteraction, ImportRun, Pin, User, utcnow
from app.storage import make_s3_client
from scripts.seed import build_hm_plan, import_plan
from scripts.train_personalization import write_training_outputs

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Real services"),
]


def test_real_image_title_encoding_normalization_title_and_batch_order():
    stream = io.BytesIO()
    Image.new("RGB", (224, 224), "#007f3f").save(stream, "PNG")
    pixels = stream.getvalue()
    encoder = ClipPinEmbedder(EmbeddingConfig(), Settings().lens_endpoint)
    pins = [
        PinContent(pin_id=str(i), title=title, image_bytes=pixels, content_hash="0" * 64)
        for i, title in enumerate(["a green shirt", "a modern living room"])
    ]
    first, second = encoder.embed(pins)
    assert first.dimension == second.dimension == 512
    assert sum(v * v for v in first.values) == pytest.approx(1)
    assert sum(a * b for a, b in zip(first.values, second.values, strict=True)) < 0.99
    assert encoder.embed([pins[0]])[0].values == pytest.approx(first.values)


def test_content_storage_title_revisions_immutable_retry_and_own_hnsw_index():
    settings = Settings()
    engine = make_engine(settings)
    stream = io.BytesIO()
    Image.new("RGB", (224, 224), "#1122bb").save(stream, "PNG")
    try:
        with Session(engine) as db:
            pin = Pin(id=str(uuid4()), title="blue shirt", original_key="unused", status="ready")
            db.add(pin)
            db.flush()
            assert store_content_embedding(db, pin, stream.getvalue(), settings)
            assert not store_content_embedding(db, pin, stream.getvalue(), settings)
            pin.title = "blue room"
            assert store_content_embedding(db, pin, stream.getvalue(), settings)
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(PinEmbedding)
                    .where(PinEmbedding.pin_id == pin.id)
                )
                == 2
            )
            definition = db.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_personalized_clip_hnsw'"
                )
            )
            assert "hnsw" in definition and "embedder:clip-image-title:v1" in definition
            assert "vector(512)" in definition and "vector_cosine_ops" in definition
            assert "dimension = 512" in definition
            db.rollback()
    finally:
        engine.dispose()


def test_personalized_cold_start_warm_snapshots_privacy_and_rollback(clients, tmp_path):
    baseline = clients()
    user_id = baseline.get("/api/auth/me").json()["id"]
    config = personalized_config(tmp_path)
    settings = Settings(feed_config=config)
    engine = make_engine(settings)
    try:
        with TestClient(create_app(settings)) as personalized:
            personalized.cookies.update(baseline.cookies)
            cold_response = personalized.get("/api/feed?limit=100")
            assert cold_response.status_code == 200, cold_response.text
            cold = cold_response.json()
            assert cold["model_versions"]["ranker"] == "ranker:popularity:v1"
            assert cold["config_version"] == config.version
            pin_id = cold["items"][-1]["pin"]["id"]
            assert (
                personalized.post(
                    "/api/events",
                    json={
                        "kind": "engagement",
                        "type": "closeup",
                        "event_id": str(uuid4()),
                        "pin_id": pin_id,
                    },
                ).status_code
                == 200
            )
            warm_response = personalized.get("/api/feed?limit=100")
            assert warm_response.status_code == 200, warm_response.text
            warm = warm_response.json()
            assert warm["model_versions"]["ranker"] == config.personalization.ranker_version
            assert warm["model_versions"]["ranker_sha256"] == config.ranker_artifact_sha256
            assert warm["model_versions"]["pin_embedder"] == EmbeddingConfig().version
            with Session(engine) as db:
                request = db.get(FeedRequest, cold["request_id"])
                assert request.context["fallback_reason"] == "no_eligible_user_embedding"
                request = db.get(FeedRequest, warm["request_id"])
                rows = list(
                    db.scalars(
                        select(ServedFeature).where(ServedFeature.request_id == request.request_id)
                    )
                )
                assert rows and all(
                    r.feature_schema_version == "features:personalized:v1" for r in rows
                )
                context = FeedContext(
                    "parity", user_id, rows[0].feature_as_of, rows[0].feature_as_of
                )
                inputs = online_inputs(db, context, config.personalization)
                for row in rows:
                    expected = inputs.features.build(user_id, row.pin_id, row.feature_as_of)
                    for name, value in expected.items():
                        assert row.features[name] == pytest.approx(value)
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(Impression)
                        .where(Impression.request_id == request.request_id)
                    )
                    == 0
                )
                target = db.get(ServedItem, (request.request_id, pin_id))
                assert target and target.retrieval_score == pytest.approx(1, abs=1e-6)
            assert personalized.put(f"/api/pins/{pin_id}/hide").status_code == 204
            hidden = personalized.get("/api/feed?limit=100").json()
            assert pin_id not in {row["pin"]["id"] for row in hidden["items"]}
            page_cursor = personalized.get("/api/feed?limit=1").json()["next_cursor"]
            assert page_cursor
            assert baseline.get("/api/feed", params={"cursor": page_cursor}).status_code == 422
        rolled_back = baseline.get("/api/feed").json()
        assert rolled_back["config_version"] == "feed:baseline:v1"
        assert rolled_back["model_versions"]["ranker"] in {
            "ranker:recency:v1",
            "ranker:popularity:v1",
        }
        with Session(engine) as db:
            assert (
                db.get(FeedRequest, warm["request_id"]).model_versions["ranker"]
                == config.personalization.ranker_version
            )
    finally:
        engine.dispose()


def test_fused_catalog_exact_and_ann_agree_on_real_same_version_corpus(clients):
    client = clients()
    user_id = client.get("/api/auth/me").json()["id"]
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            now = utcnow()
            context = FeedContext("comparison", user_id, now, now)
            catalog = catalog_vectors(db, EmbeddingConfig().version, context)
            assert len(catalog) >= 2
            query = catalog[0].embedding
            exact = ExactVectorRetriever().search(query, catalog, context, 10)
            ann = PgvectorANNRetriever().search(db, query, context, 10)
            assert {h.pin_id for h in ann} == {h.pin_id for h in exact}
            db.rollback()
    finally:
        engine.dispose()


def test_pending_save_alias_resolution_uses_actual_known_time(clients):
    client = clients()
    user_id = client.get("/api/auth/me").json()["id"]
    page = client.get("/api/feed?limit=1").json()
    pin_id = page["items"][0]["pin"]["id"]
    action_id, canonical_id, alias_id = str(uuid4()), str(uuid4()), str(uuid4())
    attribution = {"pin_id": pin_id, "request_id": page["request_id"], "position": 0}
    response = client.post(
        "/api/events",
        json=dict(
            attribution,
            kind="engagement",
            type="save",
            event_id=action_id,
            impression_event_id=alias_id,
        ),
    )
    assert response.json()["outcome"] == "pending"
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            assert load_interactions(db, user_id=user_id) == []
        for identity in (canonical_id, alias_id):
            client.post(
                "/api/events",
                json=dict(
                    attribution,
                    kind="impression",
                    event_id=identity,
                    view_rule_version="viewport:50pct:1000ms:v1",
                ),
            )
        with Session(engine) as db:
            saved = load_interactions(db, user_id=user_id)[0]
            early = db.get(EventReceipt, canonical_id).received_at
            late = db.get(EventReceipt, alias_id).received_at
            assert saved.known_at == late and saved.received_at < late
            assert saved.known_at > early
            before = FeedContext("before", user_id, early, early)
            rows = CatalogCandidateSource().retrieve(db, before)
            assert next(c.features["observed_save_count"] for c in rows if c.pin.id == pin_id) == 0
    finally:
        engine.dispose()


def test_imported_source_replay_fits_without_rewriting_live_vector_times(
    hm_folder, clients, tmp_path
):
    # Locally generated H&M-shaped fixture, not a licensed or real-user quality dataset.
    plan = build_hm_plan(hm_folder, 42, datetime(2026, 10, 7, tzinfo=UTC), 10, 10)
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    client = clients(False)
    try:
        import_plan(plan, settings)
        for article in plan.articles:
            wait_ready(client, plan.entity_id("article", article))
        now = utcnow()
        manifest = TrainingManifest(
            dataset_version="synthetic-hm-shaped-fixture:v1",
            import_run_ids=(plan.run_id,),
            cutoffs=SplitCutoffs(
                train_start="2020-09-02T00:00:00Z",
                train_end_exclusive="2020-09-03T00:00:00Z",
                validation_end_exclusive="2020-09-04T00:00:00Z",
                test_end_exclusive="2020-09-05T00:00:00Z",
            ),
            embedding_version=EmbeddingConfig().version,
            label_known_through=now,
            availability_policy="historical_import_replay",
            content_policy="fixed_import_content",
        )
        with Session(engine) as db:
            context = FeedContext("import-replay", "anonymous", now, now)
            catalog = import_catalog(db, manifest, context)
            assert len(catalog) == 2
            original = {
                row.pin_id: row.known_at
                for row in db.scalars(
                    select(PinEmbedding).where(
                        PinEmbedding.pin_id.in_([item.pin_id for item in catalog]),
                        PinEmbedding.embedder_version == manifest.embedding_version,
                    )
                )
            }
            events = load_interactions(db, import_run_ids=manifest.import_run_ids)
            replay = adapt_interactions(events, manifest)
            assert len(replay) == 5 and all(e.received_at > e.known_at for e in replay)
            report = write_training_outputs(
                catalog,
                events,
                manifest,
                tmp_path / "fitted-import",
                (tmp_path / "tracking").as_uri(),
            )
            assert report["query_count"] == 1
            assert report["examples"]["negative_shortfall"] > 0
            assert {
                row.pin_id: row.known_at
                for row in db.scalars(
                    select(PinEmbedding).where(
                        PinEmbedding.pin_id.in_(original),
                        PinEmbedding.embedder_version == manifest.embedding_version,
                    )
                )
            } == original
    finally:
        with Session(engine) as db:
            for article in plan.articles:
                delete_pin_objects(storage, settings.s3_bucket, plan.entity_id("article", article))
            db.execute(
                delete(ImportedInteraction).where(ImportedInteraction.import_run_id == plan.run_id)
            )
            db.execute(delete(Pin).where(Pin.import_run_id == plan.run_id))
            db.execute(
                delete(User).where(
                    User.id.in_(
                        [plan.entity_id("customer", customer) for customer in plan.customers],
                    )
                )
            )
            db.execute(delete(ImportRun).where(ImportRun.id == plan.run_id))
            db.commit()
        storage.close()
        engine.dispose()
