import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ctr.artifacts import CTRArtifact, load_ctr_artifact, save_ctr_artifact
from app.ctr.contracts import DatasetManifest, TimeCutoffs
from app.ctr.pipeline import HistoryContentFeatures
from app.ctr.reader import inspect_partition, read_behaviors, read_news, source_time
from app.experiments.config import FeedConfig
from app.learning import LearningExercisePending
from app.operations.contracts import BaselineManifest
from scripts.sim_baseline import load_baseline
from scripts.sim_environment import generate_environment

FIXTURE = Path(__file__).parent / "fixtures" / "mind_synthetic"


def ctr_manifest(**changes):
    return DatasetManifest(
        dataset_version="synthetic-mind:v1",
        provenance="synthetic_fixture",
        files_sha256={"train/behaviors.tsv": "0" * 64},
        source_timezone="UTC",
        cutoffs=TimeCutoffs(
            train_start=datetime(2019, 11, 13, tzinfo=UTC),
            train_end_exclusive=datetime(2019, 11, 14, tzinfo=UTC),
            validation_end_exclusive=datetime(2019, 11, 15, tzinfo=UTC),
            test_end_exclusive=datetime(2019, 11, 16, tzinfo=UTC),
        ),
        **changes,
    )


def ctr_artifact():
    return CTRArtifact(
        version="ctr:fixture:v1",
        trained_at=datetime(2026, 10, 7, tzinfo=UTC),
        coefficients=(1, 0, 0, 0),
        intercept=0,
        means=(0, 0, 0, 0),
        scales=(1, 1, 1, 1),
        training=ctr_manifest(),
        library_versions={"test": "fixture"},
    )


def test_reader_preserves_groups_empty_history_observed_labels_and_source_order():
    records = list(read_behaviors(FIXTURE / "behaviors.tsv", "train", "UTC"))
    assert len(records) == 4
    assert records[0].impression_id == "train:1"
    assert records[0].occurred_at == records[1].occurred_at
    assert records[1].history == ()
    assert [(item.news_id, item.clicked) for item in records[0].displayed] == [("N3", 1), ("N4", 0)]
    assert records[3].history == ("N99",)
    assert len(read_news(FIXTURE / "news.tsv")) == 4
    assert list(read_behaviors(FIXTURE / "behaviors.tsv", "dev", "UTC"))[0].impression_id == "dev:1"


def test_inventory_counts_and_hashes_are_not_model_metrics():
    report = inspect_partition(FIXTURE, "train", "UTC")
    assert report["counts"] == {
        "impressions": 4,
        "displayed": 8,
        "clicked": 3,
        "nonclicked": 5,
        "hidden_labels": 0,
        "cold_start_impressions": 1,
        "missing_history_references": 1,
    }
    assert (
        report["files_sha256"]["news.tsv"]
        == hashlib.sha256((FIXTURE / "news.tsv").read_bytes()).hexdigest()
    )
    assert "auc" not in report and "log_loss" not in report


def test_hidden_test_labels_are_none_never_zero(tmp_path):
    path = tmp_path / "behaviors.tsv"
    path.write_text("1\tU1\t11/13/2019 09:00:00 AM\t\tN1 N2\n")
    record = next(read_behaviors(path, "public-test", "UTC"))
    assert [item.clicked for item in record.displayed] == [None, None]


@pytest.mark.parametrize(
    "row",
    [
        "1\tU1\t11/13/2019 09:00:00 AM\t\tN1-2\n",
        "1\tU1\t11/13/2019 09:00:00 AM\t\tN1-0 N1-1\n",
        "1\tU1\t11/13/2019 09:00:00 AM\t\t\n",
        "1\tU1\t11/13/2019 09:00:00 AM\tbad-id\tN1-0\n",
        "1\tU1\t11/13/2019 09:00:00 AM\tN1-0\n",
    ],
)
def test_malformed_behavior_rows_fail_explicitly(tmp_path, row):
    path = tmp_path / "behaviors.tsv"
    path.write_text(row)
    with pytest.raises(ValueError):
        list(read_behaviors(path, "train", "UTC"))


def test_duplicate_source_impressions_are_rejected(tmp_path):
    path = tmp_path / "behaviors.tsv"
    line = "1\tU1\t11/13/2019 09:00:00 AM\t\tN1-0\n"
    path.write_text(line * 2)
    with pytest.raises(ValueError, match="duplicate"):
        list(read_behaviors(path, "train", "UTC"))


def test_source_zone_is_explicit_and_dst_ambiguity_is_rejected():
    assert source_time("11/13/2019 09:00:00 AM", "America/New_York") == datetime(
        2019, 11, 13, 14, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        source_time("11/03/2019 01:30:00 AM", "America/New_York")
    with pytest.raises(ValueError, match="nonexistent"):
        source_time("03/10/2019 02:30:00 AM", "America/New_York")


def test_ctr_artifact_roundtrip_hash_and_no_overwrite(tmp_path):
    path = tmp_path / "ctr.json"
    artifact = ctr_artifact()
    checksum = save_ctr_artifact(path, artifact)
    assert load_ctr_artifact(path, checksum) == artifact
    with pytest.raises(FileExistsError):
        save_ctr_artifact(path, artifact)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        load_ctr_artifact(path, checksum)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "logreg-artifact:v1"},
        {
            "feature_names": (
                "position",
                "category_history_fraction",
                "title_token_overlap",
                "title_length",
            )
        },
        {"coefficients": (1, 0)},
        {"scales": (1, 0, 1, 1)},
        {"intercept": float("nan")},
    ],
)
def test_ctr_artifacts_cannot_silently_use_app_schema_or_invalid_features(changes):
    with pytest.raises(ValidationError):
        CTRArtifact.model_validate({**ctr_artifact().model_dump(), **changes})


def test_learning_core_does_not_produce_fake_ctr_features():
    impression = next(read_behaviors(FIXTURE / "behaviors.tsv", "train", "UTC"))
    with pytest.raises(LearningExercisePending) as pending:
        HistoryContentFeatures().build(
            impression, "N3", read_news(FIXTURE / "news.tsv"), impression.occurred_at
        )
    assert pending.value.phase == "3B"


def test_generated_environment_is_private_idempotent_and_keeps_baseline_outside_volumes(tmp_path):
    directory = tmp_path / "control" / "pinmorph-sim-test"
    baseline = BaselineManifest(
        environment_id="pinmorph-sim-test",
        reference_time=datetime(2026, 10, 7, tzinfo=UTC),
        feed_config=FeedConfig().model_dump(mode="json"),
    )
    result = generate_environment(directory, baseline)
    env = (directory / "simulation.env").read_text()
    assert result["created"] and not result["supports_reset"]
    assert (directory / "simulation.env").stat().st_mode & 0o777 == 0o600
    assert "SIM_MODE=true" in env and "pinmorph-sim-app:local" in env and "API_PORT=8002" in env
    assert "SIM_CONTROL_TOKEN" not in str(result)
    assert not generate_environment(directory, baseline)["created"]
    assert (directory / "simulation.env").read_text() == env
    with pytest.raises(ValueError, match="different baseline"):
        generate_environment(directory, baseline.model_copy(update={"seed": 43}))


def test_baseline_seed_guard_rejects_normal_environment_wrong_hash_and_wrong_identity(tmp_path):
    baseline = BaselineManifest(
        environment_id="pinmorph-sim-test",
        reference_time=datetime(2026, 10, 7, tzinfo=UTC),
        feed_config=FeedConfig().model_dump(mode="json"),
    )
    directory = tmp_path / "control"
    result = generate_environment(directory, baseline)
    path = directory / "baseline.json"
    settings = Settings(
        _env_file=directory / "simulation.env",
        database_url="postgresql+psycopg://test:password@postgres:5432/pinmorph_sim",
        redis_url="redis://redis:6379/0",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="pinmorph-sim-media",
    )
    assert load_baseline(path, result["baseline_sha256"], settings) == baseline
    with pytest.raises(ValueError, match="disposable"):
        load_baseline(path, result["baseline_sha256"], Settings(_env_file=None))
    with pytest.raises(ValueError, match="isolated targets"):
        load_baseline(
            path, result["baseline_sha256"], Settings(_env_file=directory / "simulation.env")
        )
    with pytest.raises(ValueError, match="checksum"):
        load_baseline(path, "0" * 64, settings)
    with pytest.raises(ValueError, match="IDs"):
        load_baseline(
            path,
            result["baseline_sha256"],
            settings.model_copy(update={"sim_environment_id": "pinmorph-sim-other"}),
        )
