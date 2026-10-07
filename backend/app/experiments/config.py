from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class Arm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=80)
    buckets: int = Field(gt=0, le=10_000)
    ranker: str


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = "baseline_feed"
    version: str = "v1"
    salt: str = "pinmorph-baseline-v1"
    arms: tuple[Arm, ...] = (
        Arm(name="recency", buckets=5000, ranker="ranker:recency:v1"),
        Arm(name="popularity", buckets=5000, ranker="ranker:popularity:v1"),
    )

    @model_validator(mode="after")
    def validate_allocation(self):
        if sum(arm.buckets for arm in self.arms) != 10_000:
            raise ValueError("Experiment arms must allocate exactly 10,000 buckets")
        if len({arm.name for arm in self.arms}) != len(self.arms):
            raise ValueError("Experiment arm names must be unique")
        return self


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = "feed:baseline:v1"
    candidate_source: str = "candidate:catalog:v1"
    reranker: str = "reranker:identity:v1"
    feature_schema_version: str = "features:baseline:v1"
    interest_boost: FiniteFloat = Field(default=24, ge=0, le=1000)
    experiment: Experiment = Field(default_factory=Experiment)
