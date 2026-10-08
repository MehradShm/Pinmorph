"""Point-in-time, fitting and serving invariants beyond the original toy exercises."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_phase3_scaffold import artifact, manifest

from app.experiments.config import Arm, Experiment, FeedConfig
from app.feed.contracts import Candidate, FeedContext, RankedCandidate
from app.feed.service import FeedService
from app.ml.artifacts import save_artifact
from app.ml.config import (
    FEATURE_NAMES,
    EmbeddingConfig,
    PersonalizationConfig,
    RerankingConfig,
    RetrievalConfig,
    UserEmbeddingConfig,
)
from app.ml.contracts import (
    Embedding,
    HistoryEntry,
    Interaction,
    PinContent,
    TrainingExample,
    VectorItem,
)
from app.ml.data import adapt_interactions
from app.ml.embeddings import ClipPinEmbedder, MeanUserEmbedder
from app.ml.evaluation import catalog_coverage, ndcg_at_k, recall_at_k
from app.ml.features import PointInTimeFeatures
from app.ml.offline import evaluate_ranker
from app.ml.ranking import DiversityReranker
from app.ml.retrieval import blend_candidates
from app.ml.training import build_examples, fit_ranker
from app.models import Pin

NOW = datetime(2026, 2, 1, tzinfo=UTC)


def vector(values=(1, 0)):
    return Embedding(embedder_version="embedder:fixture:v1", values=values)


def item(pin_id, values=(1, 0)):
    return VectorItem(
        pin_id=pin_id,
        available_at=NOW - timedelta(days=60),
        known_at=NOW - timedelta(days=60),
        embedding=vector(values),
    )


def event(event_id, pin_id, time, **updates):
    return Interaction(
        **dict(
            {
                "event_id": event_id,
                "user_id": "u",
                "pin_id": pin_id,
                "occurred_at": time,
                "known_at": time,
                "received_at": time,
                "provenance": "observed_app",
                "action": "save",
            },
            **updates,
        )
    )


def receipt_manifest():
    return manifest().model_copy(
        update={
            "availability_policy": "recorded_receipt",
            "import_run_ids": (),
            "source_weights": {"observed_app": 1.0},
        }
    )


def test_user_decay_soft_cap_ties_and_canceling_history():
    history = [
        HistoryEntry(
            event_id=str(i),
            user_id="u",
            pin_id=str(i),
            occurred_at=at,
            known_at=at,
            provenance="observed_app",
            embedding=vector(values),
        )
        for i, (at, values) in enumerate(
            [
                (NOW - timedelta(hours=1), (1, 0)),
                (NOW - timedelta(hours=2), (0, 1)),
                (NOW - timedelta(hours=2), (0, 1)),
                (NOW - timedelta(hours=3), (-1, 0)),
            ]
        )
    ]
    model = MeanUserEmbedder(UserEmbeddingConfig(history_limit=2, half_life_hours=1))
    assert model.embed(history, FeedContext("r", "u", NOW, NOW)).values == pytest.approx(
        (2**-0.5, 2**-0.5),
    )
    cancellation = [
        history[0],
        history[0].model_copy(
            update={
                "event_id": "opposite",
                "embedding": vector((-1, 0)),
            }
        ),
    ]
    assert model.embed(cancellation, FeedContext("r", "u", NOW, NOW)) is None
    mismatched = history[1].model_copy(
        update={
            "embedding": Embedding(embedder_version="other", values=(0, 1)),
        }
    )
    with pytest.raises(ValueError, match="one embedding"):
        model.embed([history[0], mismatched], FeedContext("r", "u", NOW, NOW))


def test_features_exclude_tied_future_and_late_receipts_and_separate_popularity():
    old = NOW - timedelta(days=1)
    events = [
        event("old", "a", old),
        event("tied", "b", NOW),
        event("late", "b", old, known_at=NOW + timedelta(seconds=1)),
        event(
            "import",
            "a",
            old,
            user_id="other",
            provenance="imported_purchase_proxy",
            action="purchase_proxy",
            import_run_id="fixture-import",
        ),
    ]
    features = PointInTimeFeatures([item("a"), item("b", (0, 1))], events)
    a, b = features.build("u", "a", NOW), features.build("u", "b", NOW)
    assert a["similarity"] == 1 and b["similarity"] == 0
    assert a["user_history_count"] == 1
    assert a["observed_save_count"] == 1 and a["imported_purchase_count"] == 1
    assert b["observed_save_count"] == 0


def test_import_replay_retains_raw_receipt_and_rejects_undeclared_namespace():
    raw = NOW + timedelta(days=2)
    source = event(
        "purchase",
        "a",
        NOW,
        known_at=raw,
        received_at=raw,
        action="purchase_proxy",
        provenance="imported_purchase_proxy",
        import_run_id="fixture-import",
    )
    replayed = adapt_interactions([source], manifest())[0]
    assert replayed.known_at == NOW and replayed.received_at == raw
    with pytest.raises(ValueError, match="exact import"):
        adapt_interactions([source.model_copy(update={"import_run_id": "unknown"})], manifest())
    receipt = adapt_interactions([event("late", "a", NOW, known_at=raw)], receipt_manifest())[0]
    assert receipt.known_at == raw


def test_examples_are_reproducible_and_only_save_targets_are_positive():
    old = NOW - timedelta(days=10)
    events = [event("save", "a", old), event("closeup", "b", old, action="closeup")]
    catalog = [item("a"), item("b", (0, 1))]
    features = PointInTimeFeatures(catalog, events)
    examples = build_examples(events, catalog, features, receipt_manifest())
    assert examples == build_examples(
        list(reversed(events)), list(reversed(catalog)), features, receipt_manifest()
    )
    assert [(e.pin_id, e.label) for e in examples] == [("a", 1), ("b", 0)]
    assert all(e.features["user_history_count"] == 0 for e in examples)
    assert examples[0].negative_shortfall == 3
    assert examples[1].candidate_universe_size == 1
    assert examples[1].sampling_seed is not None
    assert len(examples[1].candidate_universe_sha256) == 64


def test_candidate_quotas_overlap_and_shortfall_backfill():
    def rows(ids, source):
        return [Candidate(Pin(id=p), (source,), {}) for p in ids]

    config = RetrievalConfig(pool_size=10)
    result = blend_candidates(
        rows("abcdefghi", "ann"), rows("ajklm", "popular"), rows("anopq", "recent"), config
    )
    assert [c.pin.id for c in result] == list("abcdefgjkn")
    assert result[0].sources == ("ann", "popular", "recent")
    assert len({c.pin.id for c in result}) == 10
    short = blend_candidates(
        rows("a", "ann"), rows("ab", "popular"), rows("bcdefghijk", "recent"), config
    )
    assert len(short) == 10


def test_creator_caps_missing_vectors_unknown_creators_and_actual_positions():
    candidates = [
        RankedCandidate(Candidate(Pin(id=p, owner_id=owner), ("fixture",), {}), 1, 1)
        for p, owner in [("a", "owner"), ("b", "owner"), ("c", None), ("d", None)]
    ]
    rows = DiversityReranker(RerankingConfig(per_creator_cap=1), {}).rerank(
        candidates, FeedContext("r", "u", NOW, NOW)
    )
    assert [r.candidate.pin.id for r in rows] == ["a", "c", "d"]
    assert ndcg_at_k(["a", "a", "b"], {"a", "b"}, 3) < 1
    with pytest.raises(ValueError):
        catalog_coverage([["outside"]], {"a"})
    for metric in (recall_at_k, ndcg_at_k):
        with pytest.raises(ValueError):
            metric([], set(), 0)


def training_examples():
    return [
        TrainingExample(
            user_id="u",
            pin_id=str(i),
            as_of=at,
            label=label,
            label_provenance="observed_app" if label else "sampled_unobserved",
            features={name: value if name == "similarity" else 0 for name in FEATURE_NAMES},
        )
        for i, (at, value, label) in enumerate(
            [
                (NOW - timedelta(days=10), 0, 0),
                (NOW - timedelta(days=9), 1, 1),
                (NOW - timedelta(days=8), 0, 0),
                (NOW - timedelta(days=7), 1, 1),
                (NOW, 100, 1),
                (NOW + timedelta(days=1), -100, 0),
                (NOW + timedelta(days=35), 9999, 1),
            ]
        )
    ]


def test_fitting_train_only_scaling_test_invariance_and_mlflow_tracking(tmp_path):
    examples = training_examples()
    uri = (tmp_path / "tracking").as_uri()
    trained = fit_ranker(examples, receipt_manifest(), tracking_uri=uri)
    assert trained.means[0] == 0.5 and trained.scales[0] == 0.5
    assert trained.fit_details["selection"] == "validation_log_loss"
    changed = examples[:-1] + [
        examples[-1].model_copy(
            update={
                "label": 0,
                "label_provenance": "sampled_unobserved",
                "features": {name: -9999 for name in FEATURE_NAMES},
            }
        )
    ]
    second = fit_ranker(changed, receipt_manifest(), tracking_uri=uri)
    assert trained.coefficients == second.coefficients and trained.version == second.version
    import mlflow

    runs = mlflow.search_runs(
        experiment_names=["phase3a-implicit-engagement"], output_format="list"
    )
    assert len(runs) == 2
    files = mlflow.MlflowClient().list_artifacts(runs[0].info.run_id)
    assert {f.path for f in files} == {"ranker.json", "training-manifest.json"}


def test_final_evaluation_shared_candidates_empty_targets_and_history_updates():
    catalog = [item("a"), item("b", (0, 1))]
    history = event("prior", "a", NOW - timedelta(days=1))
    first = event("test", "a", NOW + timedelta(days=35))
    cold = event("cold", "b", NOW + timedelta(days=35), user_id="cold")
    events = [history, first, cold]
    features = PointInTimeFeatures(catalog, events)
    report = evaluate_ranker(artifact(training=receipt_manifest()), events, catalog, features, k=1)
    assert report["query_count"] == 2 and set(report["cohorts"]) == {"warm", "cold"}
    assert len({q["candidate_sha256"] for q in report["queries"]}) == 1
    with pytest.raises(ValueError, match="No eligible"):
        evaluate_ranker(artifact(), [], catalog, features)


def test_clip_recipe_guard_and_order_without_network(monkeypatch):
    recipe = EmbeddingConfig()
    requests = []
    original = httpx.Client
    metadata = recipe.model_dump()
    metadata["library_versions"] = {"fixture": "v1"}

    def serve(request):
        requests.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"personalization": metadata})
        return httpx.Response(
            200, json={"embedder_version": recipe.version, "values": [1.0] + [0.0] * 511}
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(serve),
        ),
    )
    model = ClipPinEmbedder(recipe)
    assert (
        len(
            model.embed(
                [
                    PinContent(
                        pin_id="p", title="title", image_bytes=b"pixels", content_hash="0" * 64
                    )
                ]
            )
        )
        == 1
    )
    metadata["weights_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="recipe mismatch"):
        model.embed(
            [PinContent(pin_id="p", title="title", image_bytes=b"pixels", content_hash="0" * 64)]
        )
    assert requests.count("/encode-content") == 1


def personalized_config(tmp_path, record=None):
    record = record or artifact(
        training=receipt_manifest().model_copy(
            update={
                "embedding_version": EmbeddingConfig().version,
            }
        )
    )
    path = tmp_path / "ranker.json"
    digest = save_artifact(path, record)
    policy = PersonalizationConfig(ranker_version=record.version)
    return FeedConfig(
        version="feed:fixture:v1",
        candidate_source=policy.retrieval.version,
        reranker=policy.reranking.version,
        feature_schema_version=policy.feature_schema_version,
        interest_boost=0,
        personalization=policy,
        ranker_artifact_path=str(path),
        ranker_artifact_sha256=digest,
        experiment=Experiment(arms=(Arm(name="fixture", buckets=10000, ranker=record.version),)),
    )


def test_activation_rejects_checksum_and_history_policy_changes(tmp_path):
    config = personalized_config(tmp_path)
    FeedService(config)
    with pytest.raises(ValueError, match="checksum"):
        FeedService(config.model_copy(update={"ranker_artifact_sha256": "0" * 64}))
    altered = config.personalization.model_copy(
        update={
            "user_embedding": UserEmbeddingConfig(half_life_hours=1),
        }
    )
    with pytest.raises(ValueError, match="incompatible"):
        FeedService(config.model_copy(update={"personalization": altered}))
