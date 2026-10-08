from typing import Literal

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from app.ml.contracts import Record

FEATURE_NAMES = (
    "similarity",
    "age_hours",
    "observed_save_count",
    "imported_purchase_count",
    "user_history_count",
)


class EmbeddingConfig(Record):
    version: str = "embedder:clip-image-title:v1"
    architecture: str = "ViT-B/32"
    checkpoint: str = "openai:ViT-B-32"
    weights_sha256: str = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"
    dimension: int = Field(default=512, ge=1, le=2000)
    image_weight: FiniteFloat = Field(default=0.5, ge=0, le=1)
    preprocess_version: str = "openai-clip:eval224:v1"
    text_policy: str = "pin_title:truncate-eot77:v1"


class UserEmbeddingConfig(Record):
    version: str = "user_embedder:decayed-mean:v1"
    history_limit: int = Field(default=50, ge=1, le=1000)
    half_life_hours: FiniteFloat = Field(default=168, gt=0)


class RetrievalConfig(Record):
    version: str = "candidate:personalized-blend:v1"
    pool_size: int = Field(default=100, ge=1, le=1000)
    ann_share: FiniteFloat = Field(default=0.7, ge=0, le=1)
    popularity_share: FiniteFloat = Field(default=0.15, ge=0, le=1)
    recency_share: FiniteFloat = Field(default=0.15, ge=0, le=1)
    fallback_ranker: str = "ranker:popularity:v1"

    @model_validator(mode="after")
    def validate_shares(self):
        if abs(self.ann_share + self.popularity_share + self.recency_share - 1) > 1e-9:
            raise ValueError("Candidate shares must sum to one")
        if self.fallback_ranker not in {"ranker:popularity:v1", "ranker:recency:v1"}:
            raise ValueError("Cold-start fallback must be a declared baseline ranker")
        return self


class RerankingConfig(Record):
    version: str = "reranker:diversity:v1"
    duplicate_similarity: FiniteFloat = Field(default=0.95, ge=-1, le=1)
    per_creator_cap: int = Field(default=2, ge=1)


class PersonalizationConfig(Record):
    version: str = "personalization:v1"
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    user_embedding: UserEmbeddingConfig = Field(default_factory=UserEmbeddingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    reranking: RerankingConfig = Field(default_factory=RerankingConfig)
    ranker_version: str = "ranker:logreg:v1"
    feature_schema_version: str = "features:personalized:v1"


class SplitCutoffs(Record):
    train_start: AwareDatetime
    train_end_exclusive: AwareDatetime
    validation_end_exclusive: AwareDatetime
    test_end_exclusive: AwareDatetime

    @model_validator(mode="after")
    def validate_chronology(self):
        if not (
            self.train_start
            < self.train_end_exclusive
            < self.validation_end_exclusive
            < self.test_end_exclusive
        ):
            raise ValueError("Train, validation, and test cutoffs must be strictly increasing")
        return self


class TrainingManifest(Record):
    schema_version: Literal["implicit-training:v1"] = "implicit-training:v1"
    dataset_version: str = Field(min_length=1)
    import_run_ids: tuple[str, ...] = ()
    cutoffs: SplitCutoffs
    seed: int = 42
    negatives_per_positive: int = Field(default=4, ge=1, le=100)
    positive_policy: Literal["imported_purchases_and_observed_saves"] = (
        "imported_purchases_and_observed_saves"
    )
    negative_policy: Literal["eligible_at_example_time_without_future_filter"] = (
        "eligible_at_example_time_without_future_filter"
    )
    source_weights: dict[
        Literal["imported_purchase_proxy", "observed_app", "simulator"], FiniteFloat
    ] = Field(default_factory=lambda: {"imported_purchase_proxy": 1.0})
    availability_policy: Literal["historical_import_replay", "recorded_receipt"]
    tie_policy: Literal["keep_source_timestamp_ties"] = "keep_source_timestamp_ties"
    evaluation_policy: Literal["fixed_model_update_history_from_earlier_events"] = (
        "fixed_model_update_history_from_earlier_events"
    )
    embedding_version: str = Field(min_length=1)
    user_embedding: UserEmbeddingConfig = Field(default_factory=UserEmbeddingConfig)
    feature_schema_version: str = "features:personalized:v1"
    content_policy: Literal["recorded_content", "fixed_import_content"] = "recorded_content"
    label_known_through: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_sources(self):
        if not self.source_weights or any(weight <= 0 for weight in self.source_weights.values()):
            raise ValueError("Every declared data source needs a positive weight")
        if self.availability_policy == "historical_import_replay" and set(self.source_weights) != {
            "imported_purchase_proxy"
        }:
            raise ValueError("Historical import replay is only valid for imported purchase proxies")
        if len(set(self.import_run_ids)) != len(self.import_run_ids):
            raise ValueError("Import run IDs must be unique")
        if "imported_purchase_proxy" in self.source_weights and not self.import_run_ids:
            raise ValueError("Imported proxies require their exact import run IDs")
        if self.content_policy == "fixed_import_content" and (
            self.availability_policy != "historical_import_replay"
        ):
            raise ValueError("Fixed import content is only valid for historical import replay")
        return self
