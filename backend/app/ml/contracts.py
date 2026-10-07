"""Content, history, and evaluation inputs independent of a specific ML library."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from app.feed.contracts import FeedContext


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Embedding(Record):
    embedder_version: str = Field(min_length=1)
    values: tuple[FiniteFloat, ...] = Field(min_length=1, max_length=2000)

    @property
    def dimension(self) -> int:
        return len(self.values)


class PinContent(Record):
    pin_id: str
    title: str
    image_bytes: bytes
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoryEntry(Record):
    event_id: str
    user_id: str
    pin_id: str
    occurred_at: AwareDatetime
    known_at: AwareDatetime
    provenance: Literal["imported_purchase_proxy", "observed_app", "simulator"]
    embedding: Embedding


class VectorItem(Record):
    pin_id: str
    available_at: AwareDatetime
    known_at: AwareDatetime
    embedding: Embedding


class RetrievalHit(Record):
    pin_id: str
    similarity: FiniteFloat


class PinEmbedder(Protocol):
    version: str

    def embed(self, pins: list[PinContent]) -> list[Embedding]: ...


class UserEmbedder(Protocol):
    version: str

    def embed(self, history: list[HistoryEntry], context: FeedContext) -> Embedding | None: ...


class Interaction(Record):
    event_id: str
    user_id: str
    pin_id: str
    occurred_at: AwareDatetime
    known_at: AwareDatetime
    provenance: Literal["imported_purchase_proxy", "observed_app", "simulator"]
    action: Literal["purchase_proxy", "save", "closeup", "outbound_click"] = "purchase_proxy"

    @model_validator(mode="after")
    def validate_action_provenance(self):
        if (self.provenance == "imported_purchase_proxy") != (self.action == "purchase_proxy"):
            raise ValueError("Purchase proxies and observed action provenance must stay distinct")
        return self


class TrainingExample(Record):
    user_id: str
    pin_id: str
    as_of: AwareDatetime
    label: Literal[0, 1]
    label_provenance: Literal[
        "imported_purchase_proxy", "observed_app", "simulator", "sampled_unobserved"
    ]
    features: dict[str, FiniteFloat]
    sample_weight: FiniteFloat = Field(default=1, gt=0)

    @model_validator(mode="after")
    def reject_display_position(self):
        if "position" in self.features or "final_position" in self.features:
            raise ValueError("Display position cannot be an input to the v1 ranker")
        if (self.label == 0) != (self.label_provenance == "sampled_unobserved"):
            raise ValueError("Implicit-task negatives must declare sampled_unobserved provenance")
        return self


class FeatureBuilder(Protocol):
    version: str

    def build(self, user_id: str, pin_id: str, as_of: datetime) -> dict[str, float]: ...
