from pydantic import BaseModel, Field

from app.schemas import PinOut


class FeedItem(BaseModel):
    pin: PinOut
    position: int = Field(ge=0)


class FeedPage(BaseModel):
    request_id: str
    items: list[FeedItem]
    next_cursor: str | None
    model_versions: dict[str, str]
    config_version: str
    experiment_arms: dict[str, str]
