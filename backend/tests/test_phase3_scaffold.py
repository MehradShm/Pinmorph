import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.feed.contracts import FeedContext
from app.ml.artifacts import RankerArtifact, load_artifact, save_artifact
from app.ml.config import (
    FEATURE_NAMES,
    EmbeddingConfig,
    RetrievalConfig,
    SplitCutoffs,
    TrainingManifest,
    UserEmbeddingConfig,
)
from app.ml.contracts import Embedding, Interaction, TrainingExample
from app.ml.embeddings import ClipPinEmbedder, MeanUserEmbedder
from scripts.phase3_preflight import pending_exercises


def manifest():
    return TrainingManifest(
        dataset_version="fixture:v1",
        import_run_ids=("fixture-import",),
        cutoffs=SplitCutoffs(
            train_start="2026-01-01T00:00:00Z",
            train_end_exclusive="2026-02-01T00:00:00Z",
            validation_end_exclusive="2026-03-01T00:00:00Z",
            test_end_exclusive="2026-04-01T00:00:00Z",
        ),
        availability_policy="historical_import_replay",
        embedding_version="embedder:fixture:v1",
    )


def artifact(**changes):
    return RankerArtifact(
        **{
            "version": "ranker:fixture:v1",
            "trained_at": datetime(2026, 4, 2, tzinfo=UTC),
            "coefficients": (1, 0, 0, 0, 0),
            "intercept": 0,
            "means": (0, 0, 0, 0, 0),
            "scales": (1, 1, 1, 1, 1),
            "training": manifest(),
            "library_versions": {"fixture": "v1"},
            **changes,
        }
    )


def test_manifest_rejects_future_leaking_source_policy_and_invalid_cutoffs():
    body = manifest().model_dump(mode="json")
    with pytest.raises(ValidationError, match="only valid"):
        TrainingManifest.model_validate({**body, "source_weights": {"observed_app": 1}})
    with pytest.raises(ValidationError, match="exact import"):
        TrainingManifest.model_validate({**body, "import_run_ids": []})
    body["cutoffs"]["validation_end_exclusive"] = body["cutoffs"]["train_end_exclusive"]
    with pytest.raises(ValidationError, match="strictly increasing"):
        TrainingManifest.model_validate(body)


def test_live_receipt_policy_can_declare_observed_only_data_without_imports():
    body = manifest().model_dump(mode="json")
    record = TrainingManifest.model_validate(
        {
            **body,
            "source_weights": {"observed_app": 1},
            "import_run_ids": [],
            "availability_policy": "recorded_receipt",
        }
    )
    assert record.import_run_ids == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"coefficients": (1,)},
        {"means": (0,)},
        {"scales": (0, 1, 1, 1, 1)},
        {"intercept": float("nan")},
        {"feature_names": (*FEATURE_NAMES[:-1], "position")},
    ],
)
def test_artifact_rejects_incompatible_or_nonfinite_scoring_contracts(changes):
    with pytest.raises(ValidationError):
        artifact(**changes)


def test_artifact_publication_roundtrip_tampering_and_no_overwrite(tmp_path):
    path = tmp_path / "models" / "ranker.json"
    record = artifact()
    digest = save_artifact(path, record)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_artifact(path, digest) == record
    with pytest.raises(FileExistsError):
        save_artifact(path, artifact(intercept=2))
    assert load_artifact(path, digest) == record
    path.write_text(path.read_text().replace('"intercept":0.0', '"intercept":3.0'))
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(path, digest)
    assert list(path.parent.glob(".ranker-*")) == []


def test_feature_position_and_implicit_negative_provenance_are_rejected():
    body = {
        "user_id": "u",
        "pin_id": "p",
        "as_of": datetime.now(UTC),
        "label": 0,
        "label_provenance": "sampled_unobserved",
        "features": {"similarity": 0},
    }
    assert TrainingExample.model_validate(body).label == 0
    with pytest.raises(ValidationError, match="Display position"):
        TrainingExample.model_validate({**body, "features": {"position": 1}})
    with pytest.raises(ValidationError, match="sampled_unobserved"):
        TrainingExample.model_validate({**body, "label_provenance": "imported_purchase_proxy"})


def test_imported_proxies_cannot_be_mislabeled_as_observed_actions():
    body = {
        "event_id": "e",
        "user_id": "u",
        "pin_id": "p",
        "occurred_at": datetime.now(UTC),
        "known_at": datetime.now(UTC),
        "provenance": "imported_purchase_proxy",
    }
    assert Interaction.model_validate(body).action == "purchase_proxy"
    with pytest.raises(ValidationError, match="stay distinct"):
        Interaction.model_validate({**body, "action": "save"})
    with pytest.raises(ValidationError, match="stay distinct"):
        Interaction.model_validate({**body, "provenance": "observed_app"})


def test_vector_and_retrieval_config_boundaries():
    with pytest.raises(ValidationError):
        Embedding(embedder_version="v1", values=(1, float("inf")))
    with pytest.raises(ValidationError):
        RetrievalConfig(ann_share=1)


def test_inventory_is_static_and_groups_shared_exercises(tmp_path):
    (tmp_path / "exercise.py").write_text(
        'raise RuntimeError("must never execute this file")\n'
        'def a():\n  raise LearningExercisePending("example", phase="3A")\n'
        'def b():\n  raise LearningExercisePending("example", phase="3A")\n'
    )
    records = pending_exercises(tmp_path)
    assert len(records) == 1 and records[0]["phase"] == "3A"
    assert len(records[0]["locations"]) == 2


def test_empty_ml_inputs_do_not_download_weights_or_return_fake_vectors():
    assert ClipPinEmbedder(EmbeddingConfig()).embed([]) == []
    now = datetime.now(UTC)
    assert (
        MeanUserEmbedder(UserEmbeddingConfig()).embed([], FeedContext("r", "u", now, now)) is None
    )
