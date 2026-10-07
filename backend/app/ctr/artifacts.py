from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from app.artifact_io import publish_bytes, verified_bytes
from app.ctr.contracts import FEATURE_NAMES, DatasetManifest, Record


class CTRArtifact(Record):
    schema_version: Literal["mind-ctr-logreg:v1"] = "mind-ctr-logreg:v1"
    version: str = Field(min_length=1)
    trained_at: AwareDatetime
    feature_names: tuple[str, ...] = FEATURE_NAMES
    coefficients: tuple[FiniteFloat, ...]
    intercept: FiniteFloat
    means: tuple[FiniteFloat, ...]
    scales: tuple[FiniteFloat, ...]
    training: DatasetManifest
    library_versions: dict[str, str]

    @model_validator(mode="after")
    def validate_feature_order(self):
        count = len(FEATURE_NAMES)
        if len(self.feature_names) != count or set(self.feature_names) != set(FEATURE_NAMES):
            raise ValueError("CTR artifact requires exactly its own declared features")
        if any(len(values) != count for values in (self.coefficients, self.means, self.scales)):
            raise ValueError("CTR coefficients/scaling must match feature order")
        if any(scale <= 0 for scale in self.scales):
            raise ValueError("CTR feature scales must be positive")
        return self


def save_ctr_artifact(path: Path, artifact: CTRArtifact) -> str:
    return publish_bytes(path, artifact.model_dump_json().encode())


def load_ctr_artifact(path: Path, expected_sha256: str) -> CTRArtifact:
    return CTRArtifact.model_validate_json(verified_bytes(path, expected_sha256))
