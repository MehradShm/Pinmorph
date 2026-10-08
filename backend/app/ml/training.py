import hashlib
import json
import math
import random
import warnings
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from app.ml.artifacts import RankerArtifact
from app.ml.config import FEATURE_NAMES, SplitCutoffs, TrainingManifest
from app.ml.contracts import FeatureBuilder, Interaction, TrainingExample, VectorItem


def split_interactions(
    interactions: list[Interaction], cutoffs: SplitCutoffs
) -> dict[str, list[Interaction]]:
    """Half-open chronological splits; exclude outside range and keep occurrence ties together."""
    splits = {"train": [], "validation": [], "test": []}
    if len({e.event_id for e in interactions}) != len(interactions):
        raise ValueError("Duplicate interaction identity")
    for event in sorted(interactions, key=lambda e: (e.occurred_at, e.event_id)):
        name = split_name(event.occurred_at, cutoffs)
        if name:
            splits[name].append(event)
    return splits


def split_name(time, cutoffs):
    if cutoffs.train_start <= time < cutoffs.train_end_exclusive:
        return "train"
    if cutoffs.train_end_exclusive <= time < cutoffs.validation_end_exclusive:
        return "validation"
    if cutoffs.validation_end_exclusive <= time < cutoffs.test_end_exclusive:
        return "test"
    return None


def build_examples(
    interactions: list[Interaction],
    catalog: list[VectorItem],
    features: FeatureBuilder,
    manifest: TrainingManifest,
) -> list[TrainingExample]:
    """Eligible point-in-time positives and seeded sampled-unobserved negatives.

    Target positives follow the manifest: imported purchases and observed/simulated saves;
    closeups/source clicks may inform history but are not this dataset's positive target.
    Only declared source weights participate. Build history strictly before each example;
    use the manifest's explicit availability policy. In historical_import_replay, an
    adapter maps imported source chronology to known times while preserving raw receipt;
    never apply that policy to delayed observed/simulator events. Never filter a negative
    using future interactions. Record candidate universe, seed and shortfalls. No labels
    for unseen served items, unresolved actions, or open impression windows.
    """
    if features.version != manifest.feature_schema_version:
        raise ValueError("Feature builder does not match training manifest")
    if len({item.pin_id for item in catalog}) != len(catalog):
        raise ValueError("Duplicate catalog pin identity")
    if len({e.event_id for e in interactions}) != len(interactions):
        raise ValueError("Duplicate interaction identity")
    examples = []
    for event in sorted(interactions, key=lambda e: (e.occurred_at, e.event_id)):
        if event.provenance not in manifest.source_weights or event.action not in {
            "save",
            "purchase_proxy",
        }:
            continue
        if not split_name(event.occurred_at, manifest.cutoffs):
            continue
        if manifest.availability_policy == "historical_import_replay":
            if (
                event.provenance != "imported_purchase_proxy"
                or event.import_run_id not in manifest.import_run_ids
            ):
                raise ValueError("Historical replay requires declared imported source events")
            if event.known_at != event.occurred_at or event.received_at is None:
                raise ValueError("Use the import adapter and preserve raw receipt before replay")
        known_through = manifest.label_known_through or manifest.cutoffs.test_end_exclusive
        if max(event.received_at or event.known_at, event.known_at) > known_through:
            continue
        eligible = sorted(
            item.pin_id
            for item in catalog
            if item.available_at <= event.occurred_at
            and item.known_at <= event.occurred_at
            and item.embedding.embedder_version == manifest.embedding_version
        )
        if event.pin_id not in eligible:
            continue
        # Exclude this target only. Tied/later positives never alter this event's universe.
        universe = [pin_id for pin_id in eligible if pin_id != event.pin_id]
        payload = json.dumps([manifest.seed, event.event_id], separators=(",", ":"))
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
        count = min(manifest.negatives_per_positive, len(universe))
        negatives = random.Random(seed).sample(universe, count)
        common = {
            "user_id": event.user_id,
            "as_of": event.occurred_at,
            "sample_weight": manifest.source_weights[event.provenance],
            "target_event_id": event.event_id,
            "sampling_seed": seed,
            "candidate_universe_sha256": hashlib.sha256(json.dumps(universe).encode()).hexdigest(),
            "candidate_universe_size": len(universe),
            "negative_shortfall": manifest.negatives_per_positive - count,
        }
        examples.append(
            TrainingExample(
                **common,
                pin_id=event.pin_id,
                label=1,
                label_provenance=event.provenance,
                features=features.build(event.user_id, event.pin_id, event.occurred_at),
            )
        )
        examples.extend(
            TrainingExample(
                **common,
                pin_id=pin_id,
                label=0,
                label_provenance="sampled_unobserved",
                features=features.build(event.user_id, pin_id, event.occurred_at),
            )
            for pin_id in negatives
        )
    return examples


def fit_ranker(
    examples: list[TrainingExample],
    manifest: TrainingManifest,
    *,
    tracking_uri: str | None = None,
    regularization: tuple[float, ...] = (0.1, 1.0, 10.0),
) -> RankerArtifact:
    """Fit train-only scaling and weighted logistic regression; reject empty/single-class data.

    Hyperparameters use validation only, final test stays separate. Export ordered features,
    scaling and coefficients to JSON, record sklearn/runtime versions, and track the run in
    MLflow with the full manifest. Fitting does not activate a model or replace a feed config.
    """
    train = [e for e in examples if split_name(e.as_of, manifest.cutoffs) == "train"]
    validation = [e for e in examples if split_name(e.as_of, manifest.cutoffs) == "validation"]
    if not train or {e.label for e in train} != {0, 1}:
        raise ValueError("Training needs nonempty data with both classes")
    if not regularization or any(c <= 0 or not math.isfinite(c) for c in regularization):
        raise ValueError("Regularization values must be positive")
    for e in train + validation:
        if set(e.features) != set(FEATURE_NAMES):
            raise ValueError("Examples must match the declared feature schema")
        if e.label == 1 and e.label_provenance not in manifest.source_weights:
            raise ValueError("Undeclared positive source")
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    x = np.asarray([[e.features[name] for name in FEATURE_NAMES] for e in train])
    y = np.asarray([e.label for e in train])
    weights = np.asarray([e.sample_weight for e in train])
    scaler = StandardScaler().fit(x)  # Never fit on validation or final test.
    transformed = scaler.transform(x)
    trials, fitted = [], []
    for c in sorted(set(regularization)):
        model = LogisticRegression(C=c, solver="lbfgs", max_iter=1000, random_state=manifest.seed)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model.fit(transformed, y, sample_weight=weights)
        loss = None
        if validation:
            vx = np.asarray([[e.features[name] for name in FEATURE_NAMES] for e in validation])
            loss = float(
                log_loss(
                    [e.label for e in validation],
                    model.predict_proba(scaler.transform(vx)),
                    sample_weight=[e.sample_weight for e in validation],
                    labels=[0, 1],
                )
            )
        trials.append({"C": c, "validation_log_loss": loss})
        fitted.append(model)
    selected = min(
        range(len(trials)),
        key=lambda i: (
            trials[i]["validation_log_loss"] if validation else 0,
            trials[i]["C"],
        ),
    )
    model = fitted[selected]
    # The semantic version is bound to inputs/options/coefficients, not a mutable filename.
    identity = json.dumps(
        {
            "manifest": manifest.model_dump(mode="json"),
            "examples": [e.model_dump(mode="json") for e in train + validation],
            "trials": trials,
            "coefficients": model.coef_[0].tolist(),
            "intercept": float(model.intercept_[0]),
            "means": scaler.mean_.tolist(),
            "scales": scaler.scale_.tolist(),
            "library_versions": {name: version(name) for name in ("numpy", "scikit-learn")},
        },
        sort_keys=True,
    ).encode()
    record = RankerArtifact(
        version="ranker:logreg:" + hashlib.sha256(identity).hexdigest()[:16],
        trained_at=datetime.now(UTC),
        coefficients=tuple(model.coef_[0]),
        intercept=float(model.intercept_[0]),
        means=tuple(scaler.mean_),
        scales=tuple(scaler.scale_),
        training=manifest,
        library_versions={
            name: version(name) for name in ("numpy", "scikit-learn", "mlflow-skinny")
        },
        fit_details={
            "train_examples": len(train),
            "validation_examples": len(validation),
            "trials": trials,
            "selected_C": trials[selected]["C"],
            "selection": "validation_log_loss" if validation else "smallest_C_no_validation",
        },
    )
    return track_training(record, tracking_uri)


def track_training(artifact, tracking_uri):
    import mlflow

    if tracking_uri is None:
        Path("mlruns").mkdir(exist_ok=True)
        tracking_uri = "sqlite:///mlruns/phase3a.db"
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("phase3a-implicit-engagement")
    with mlflow.start_run(run_name=artifact.version) as run:
        artifact = artifact.model_copy(
            update={
                "fit_details": dict(
                    artifact.fit_details,
                    mlflow_run_id=run.info.run_id,
                )
            }
        )
        mlflow.log_params(
            {
                "dataset_version": artifact.training.dataset_version,
                "embedding_version": artifact.training.embedding_version,
                "feature_schema_version": artifact.training.feature_schema_version,
                "seed": artifact.training.seed,
                "selected_C": artifact.fit_details["selected_C"],
                "task": "implicit_engagement_not_ctr",
            }
        )
        for trial in artifact.fit_details["trials"]:
            if trial["validation_log_loss"] is not None:
                mlflow.log_metric(
                    "validation_log_loss",
                    trial["validation_log_loss"],
                    step=artifact.fit_details["trials"].index(trial),
                )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ranker.json"
            path.write_text(artifact.model_dump_json())
            mlflow.log_artifact(str(path))
            manifest_path = Path(directory) / "training-manifest.json"
            manifest_path.write_text(artifact.training.model_dump_json())
            mlflow.log_artifact(str(manifest_path))
    return artifact
