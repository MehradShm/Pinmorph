"""Inspectable JSON ranker artifacts: ordered inputs, train-only scaling, and provenance."""

import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from app.ml.config import FEATURE_NAMES, TrainingManifest
from app.ml.contracts import Record


class RankerArtifact(Record):
    schema_version: Literal["logreg-artifact:v1"] = "logreg-artifact:v1"
    version: str = Field(min_length=1)
    trained_at: AwareDatetime
    feature_names: tuple[str, ...] = FEATURE_NAMES
    coefficients: tuple[FiniteFloat, ...]
    intercept: FiniteFloat
    means: tuple[FiniteFloat, ...]
    scales: tuple[FiniteFloat, ...]
    training: TrainingManifest
    library_versions: dict[str, str]

    @model_validator(mode="after")
    def validate_feature_contract(self):
        count = len(self.feature_names)
        if set(self.feature_names) != set(FEATURE_NAMES) or count != len(FEATURE_NAMES):
            raise ValueError("The v1 artifact requires exactly the declared scoring features")
        if any(len(values) != count for values in (self.coefficients, self.means, self.scales)):
            raise ValueError("Coefficients, means, and scales must match the ordered feature names")
        if any(scale <= 0 for scale in self.scales):
            raise ValueError("Feature scales must be positive")
        return self


def artifact_bytes(artifact: RankerArtifact) -> bytes:
    return artifact.model_dump_json().encode("utf-8")


def artifact_digest(artifact: RankerArtifact) -> str:
    return hashlib.sha256(artifact_bytes(artifact)).hexdigest()


def save_artifact(path: Path, artifact: RankerArtifact) -> str:
    """Publish complete bytes without overwriting an existing artifact, even under a race."""
    payload = artifact_bytes(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".ranker-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard link publishes atomically and rejects existing destinations.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def load_artifact(path: Path, expected_sha256: str) -> RankerArtifact:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Ranker artifact checksum does not match the pinned version")
    return RankerArtifact.model_validate_json(payload)
