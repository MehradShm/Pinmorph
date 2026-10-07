from datetime import datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

FEATURE_NAMES = (
    "history_length",
    "category_history_fraction",
    "title_token_overlap",
    "title_length",
)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class News(Record):
    news_id: str = Field(pattern=r"^N[0-9]+$")
    category: str
    subcategory: str
    title: str
    abstract: str


class DisplayedNews(Record):
    news_id: str = Field(pattern=r"^N[0-9]+$")
    clicked: Literal[0, 1] | None  # Public test data can have hidden labels; never infer zero.


class Impression(Record):
    impression_id: str = Field(min_length=1)  # Namespaced by the source partition.
    user_id: str = Field(pattern=r"^U[0-9]+$")
    occurred_at: AwareDatetime
    history: tuple[str, ...]
    displayed: tuple[DisplayedNews, ...] = Field(min_length=1)
    source_partition: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_candidates(self):
        ids = [item.news_id for item in self.displayed]
        if len(ids) != len(set(ids)):
            raise ValueError("An impression cannot repeat a candidate news ID")
        return self


class TimeCutoffs(Record):
    train_start: AwareDatetime
    train_end_exclusive: AwareDatetime
    validation_end_exclusive: AwareDatetime
    test_end_exclusive: AwareDatetime

    @model_validator(mode="after")
    def chronological(self):
        if not (
            self.train_start
            < self.train_end_exclusive
            < self.validation_end_exclusive
            < self.test_end_exclusive
        ):
            raise ValueError("CTR cutoffs must be strictly increasing")
        return self


class DatasetManifest(Record):
    schema_version: Literal["mind-ctr-dataset:v1"] = "mind-ctr-dataset:v1"
    dataset_version: str = Field(min_length=1)
    provenance: Literal["mind_observed", "synthetic_fixture"]
    files_sha256: dict[str, str] = Field(min_length=1)
    source_timezone: str  # A declared assumption: MIND source strings do not contain offsets.
    timestamp_policy: Literal["naive_source_assumed_zone"] = "naive_source_assumed_zone"
    cutoffs: TimeCutoffs
    seed: int = 42
    label_policy: Literal["all_displayed_source_click_labels"] = "all_displayed_source_click_labels"
    feature_schema: Literal["ctr:history-content:v1"] = "ctr:history-content:v1"
    history_policy: Literal["source_pre_impression_history_only"] = (
        "source_pre_impression_history_only"
    )
    position_policy: Literal["exclude_shuffled_source_order"] = "exclude_shuffled_source_order"
    transform_policy: Literal["fit_train_only"] = "fit_train_only"
    baseline: Literal["training_period_constant_click_rate"] = "training_period_constant_click_rate"

    @model_validator(mode="after")
    def validate_sources(self):
        try:
            ZoneInfo(self.source_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Declare a valid IANA source timezone") from exc
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in self.files_sha256.values()
        ):
            raise ValueError("Input file hashes must be SHA-256 hex digests")
        return self


class CTRExample(Record):
    impression_id: str
    news_id: str
    occurred_at: AwareDatetime
    label: Literal[0, 1]
    features: dict[str, FiniteFloat]

    @model_validator(mode="after")
    def feature_contract(self):
        if set(self.features) != set(FEATURE_NAMES):
            raise ValueError("CTR examples require exactly the declared non-position features")
        return self


class Prediction(Record):
    impression_id: str
    news_id: str
    label: Literal[0, 1]
    probability: FiniteFloat = Field(ge=0, le=1)


class CTRPredictor(Protocol):
    version: str

    def predict(self, examples: list[CTRExample]) -> list[float]: ...


class CTRFeatureBuilder(Protocol):
    version: str

    def build(
        self, impression: Impression, news_id: str, news: dict[str, News], as_of: datetime
    ) -> dict[str, float]: ...
