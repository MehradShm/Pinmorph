from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

VIEW_RULE_VERSION = "viewport:50pct:1000ms:v1"


class EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    pin_id: UUID
    client_event_time: AwareDatetime | None = None


class ImpressionEvent(EventBase):
    kind: Literal["impression"]
    request_id: UUID
    position: int = Field(ge=0, strict=True)
    view_rule_version: Literal["viewport:50pct:1000ms:v1"]


class EngagementEvent(EventBase):
    kind: Literal["engagement"]
    type: Literal["closeup", "save", "outbound_click"]
    request_id: UUID | None = None
    position: int | None = Field(default=None, ge=0, strict=True)
    impression_event_id: UUID | None = None

    @model_validator(mode="after")
    def complete_attribution(self):
        if (self.request_id is None) != (self.position is None):
            raise ValueError("request_id and position must be supplied together")
        if self.impression_event_id is not None and self.request_id is None:
            raise ValueError("An impression reference requires served-item attribution")
        return self


EventInput = Annotated[ImpressionEvent | EngagementEvent, Field(discriminator="kind")]


class EventResult(BaseModel):
    event_id: UUID
    outcome: Literal["accepted", "duplicate", "duplicate_view", "pending", "unattributed"]
