from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class BaselineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["sim-baseline:v1"] = "sim-baseline:v1"
    environment_id: str = Field(pattern=r"^pinmorph-sim-[a-z0-9][a-z0-9-]{0,30}$")
    dataset: Literal["synthetic_demo"] = "synthetic_demo"
    seed: int = 42
    reference_time: AwareDatetime
    catalog_size: int = Field(default=32, ge=1, le=32)
    feed_config: dict
    model_artifacts: tuple[str, ...] = ()
    time_mode: Literal["wall"] = "wall"
    readiness: Literal["infrastructure_only"] = "infrastructure_only"
    # No click history, model weights, feed acceptance or reset receipt is invented here.


class RunManifest(BaseModel):
    """Future registration schema; validation alone does not register or activate a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["sim-run:v1"] = "sim-run:v1"
    run_id: str = Field(min_length=1, max_length=36)
    environment_id: str = Field(pattern=r"^pinmorph-sim-[a-z0-9][a-z0-9-]{0,30}$")
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str = Field(min_length=1)
    seed: int
    config_version: str = Field(min_length=1)
    model_versions: dict[str, str]
    time_mode: Literal["wall"] = "wall"
    registered_at: AwareDatetime
