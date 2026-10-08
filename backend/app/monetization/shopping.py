"""Product eligibility and filter-bound shopping pages, separate from feed ranking."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.models import Pin, User
from app.monetization.models import PinProduct
from app.monetization.schemas import Currency
from app.search.service import SearchQuery


def shop_condition():
    return (
        select(PinProduct.pin_id)
        .join(User, User.id == Pin.owner_id)
        .where(
            PinProduct.pin_id == Pin.id,
            User.is_business.is_(True),
            PinProduct.availability.in_(["in_stock", "preorder"]),
        )
        .correlate(Pin)
        .exists()
    )


class ShopQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    surface: Literal["shop"] = "shop"
    q: str = Field(default="", max_length=200)
    currency: Currency | None = None
    viewer_id: str | None = None

    @model_validator(mode="after")
    def normalized_query(self):
        value = self.q.strip()
        if value:
            value = SearchQuery(q=value).q
        object.__setattr__(self, "q", value)
        return self

    def fingerprint(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
