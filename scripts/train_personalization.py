"""Fit/evaluate declared imports or an explicitly synthetic mechanics validation trace."""

import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.artifact_io import publish_bytes
from app.config import Settings
from app.database import make_engine
from app.experiments.config import Arm, Experiment, FeedConfig
from app.feed.contracts import FeedContext
from app.ml.artifacts import save_artifact
from app.ml.config import PersonalizationConfig, SplitCutoffs, TrainingManifest
from app.ml.contracts import Interaction
from app.ml.data import adapt_interactions, import_catalog, load_interactions
from app.ml.features import PointInTimeFeatures
from app.ml.offline import evaluate_ranker
from app.ml.training import build_examples, fit_ranker
from app.ml.vector_store import catalog_vectors
from app.models import utcnow


def validation_trace(catalog):
    """Authored fixture, never written as app history or used to infer real preferences."""
    start = max(item.available_at for item in catalog) + timedelta(days=1)
    start = max(start, max(item.known_at for item in catalog) + timedelta(days=1))
    ids = sorted(item.pin_id for item in catalog)
    events = []
    for day in range(12):
        for user in range(8):
            at = start + timedelta(days=day, hours=user)
            # Two repeatedly visited fixture pins per authored account; no preference engine.
            pin_id = ids[(user * 3 + day % 2) % len(ids)]
            events.append(
                Interaction(
                    event_id=f"fixture-day{day}-user{user}",
                    user_id=f"fixture-user{user}",
                    pin_id=pin_id,
                    occurred_at=at,
                    known_at=at + timedelta(seconds=1),
                    received_at=at + timedelta(seconds=1),
                    provenance="simulator",
                    action="save",
                )
            )
    # Separate cold-start test account.
    at = start + timedelta(days=10, hours=9)
    events.append(
        Interaction(
            event_id="fixture-cold",
            user_id="fixture-cold",
            pin_id=ids[-1],
            occurred_at=at,
            known_at=at,
            received_at=at,
            provenance="simulator",
            action="save",
        )
    )
    manifest = TrainingManifest(
        dataset_version="synthetic-mechanics-trace:v1",
        cutoffs=SplitCutoffs(
            train_start=start,
            train_end_exclusive=start + timedelta(days=6),
            validation_end_exclusive=start + timedelta(days=9),
            test_end_exclusive=start + timedelta(days=12),
        ),
        availability_policy="recorded_receipt",
        source_weights={"simulator": 1.0},
        embedding_version=PersonalizationConfig().embedding.version,
    )
    return events, manifest


def write_training_outputs(catalog, events, manifest, output, tracking_uri=None):
    output.mkdir(parents=True, exist_ok=True)
    events = adapt_interactions(events, manifest)
    features = PointInTimeFeatures(catalog, events, manifest.user_embedding)
    examples = build_examples(events, catalog, features, manifest)
    artifact = fit_ranker(examples, manifest, tracking_uri=tracking_uri)
    report = evaluate_ranker(artifact, events, catalog, features)
    digest = save_artifact(output / "ranker.json", artifact)
    # The read-only Docker mount is consumed by a different local UID.
    (output / "ranker.json").chmod(0o644)
    policy = PersonalizationConfig(
        ranker_version=artifact.version, user_embedding=manifest.user_embedding
    )
    config = FeedConfig(
        version="feed:personalized:" + digest[:16],
        candidate_source=policy.retrieval.version,
        reranker=policy.reranking.version,
        feature_schema_version=policy.feature_schema_version,
        interest_boost=0,
        personalization=policy,
        ranker_artifact_path=str(output / "ranker.json"),
        ranker_artifact_sha256=digest,
        experiment=Experiment(
            name="personalized_feed",
            version=digest[:16],
            salt="phase3a-personalized-v1",
            arms=(Arm(name="logreg", buckets=10000, ranker=artifact.version),),
        ),
    )
    report["artifact_sha256"] = digest
    report["dataset_sha256"] = hashlib.sha256(
        json.dumps(
            [e.model_dump(mode="json") for e in events],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    report["examples"] = {
        "total": len(examples),
        "positives": sum(e.label for e in examples),
        "negative_shortfall": sum(e.negative_shortfall for e in examples if e.label),
        "sampling_policy": manifest.negative_policy,
        "seed": manifest.seed,
    }
    report["corpus_sha256"] = hashlib.sha256(
        json.dumps(
            [
                item.model_dump(mode="json")
                for item in sorted(catalog, key=lambda item: item.pin_id)
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    report["embedding_dimension"] = catalog[0].embedding.dimension
    report["embedding_recipe"] = policy.embedding.model_dump(mode="json")
    if manifest.dataset_version == "synthetic-mechanics-trace:v1":
        report["data_provenance"] = "synthetic_validation_fixture"
        report["limitations"].insert(
            0, "Authored synthetic trace: no real-user quality conclusion."
        )
    elif set(manifest.source_weights) == {"imported_purchase_proxy"}:
        report["data_provenance"] = "declared_imported_purchase_proxies"
    else:
        report["data_provenance"] = "declared_resolved_actions_and_source_weights"
    publish_bytes(output / "evaluation.json", (json.dumps(report, indent=2) + "\n").encode())
    publish_bytes(output / "feed-config.json", (config.model_dump_json(indent=2) + "\n").encode())
    publish_bytes(
        output / "training-manifest.json", (manifest.model_dump_json(indent=2) + "\n").encode()
    )
    audit = [e.model_dump(mode="json", exclude={"features"}) for e in examples if e.label]
    publish_bytes(output / "sampling-audit.json", (json.dumps(audit, indent=2) + "\n").encode())
    import mlflow

    with mlflow.start_run(run_id=artifact.fit_details["mlflow_run_id"]):
        mlflow.set_tag("data_provenance", report["data_provenance"])
        mlflow.log_param("corpus_sha256", report["corpus_sha256"])
        mlflow.log_param("dataset_sha256", report["dataset_sha256"])
        for method, metrics in report["methods"].items():
            for metric in ("recall_at_k", "ndcg_at_k", "catalog_coverage"):
                mlflow.log_metric(f"test_{method}_{metric}", metrics[metric])
        mlflow.log_artifact(str(output / "evaluation.json"))
        mlflow.log_artifact(str(output / "sampling-audit.json"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic-validation", action="store_true")
    source.add_argument(
        "--manifest", type=Path, help="Explicit training manifest for imports or resolved actions"
    )
    parser.add_argument("--output", type=Path, required=True, help="New immutable run directory")
    parser.add_argument("--tracking-uri")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new run directory")
    settings = Settings()
    engine = make_engine(settings)
    now = utcnow()
    context = FeedContext("offline-training", "anonymous", now, now)
    try:
        with Session(engine) as db:
            if args.synthetic_validation:
                catalog = catalog_vectors(db, PersonalizationConfig().embedding.version, context)
                if len(catalog) < 2:
                    raise ValueError("Backfill at least two real CLIP content vectors first")
                events, manifest = validation_trace(catalog)
            else:
                manifest = TrainingManifest.model_validate_json(args.manifest.read_bytes())
                catalog = (
                    import_catalog(db, manifest, context)
                    if manifest.availability_policy == "historical_import_replay"
                    else catalog_vectors(db, manifest.embedding_version, context)
                )
                events = load_interactions(db, import_run_ids=manifest.import_run_ids)
            report = write_training_outputs(
                catalog, events, manifest, args.output, args.tracking_uri
            )
            db.rollback()  # Fitting/evaluation create no app events, users or serving requests.
        print(
            json.dumps(
                {
                    "model_version": report["model_version"],
                    "artifact_sha256": report["artifact_sha256"],
                    "query_count": report["query_count"],
                    "methods": report["methods"],
                    "output": str(args.output),
                    "activated": False,
                },
                indent=2,
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
