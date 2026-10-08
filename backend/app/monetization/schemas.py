from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Currency = Literal["USD", "CAD", "EUR", "GBP", "AUD", "NZD", "SEK", "DKK"]
Availability = Literal["in_stock", "out_of_stock", "preorder", "discontinued"]
Traffic = Literal["app", "simulator"]


def clean_url(value):
    if value and (value.username or value.password or len(str(value)) > 2000):
        raise ValueError("Use a public website link without credentials (maximum 2000 characters)")
    return value


class BusinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str = Field(min_length=1, max_length=120)
    website: HttpUrl | None = None

    @field_validator("business_name")
    @classmethod
    def name(cls, value):
        if not value.strip():
            raise ValueError("A business name is required")
        return value.strip()

    _website = field_validator("website")(clean_url)


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Currency
    availability: Availability = "in_stock"
    merchant_url: HttpUrl

    _url = field_validator("merchant_url")(clean_url)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    price: Decimal
    currency: Currency
    availability: Availability
    merchant_url: str


class AdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["ads:placeholders:v1"] = "ads:placeholders:v1"
    enabled: bool = True
    after_every: int = Field(default=8, ge=2, le=100)
    max_slots: int = Field(default=2, ge=0, le=10)


class AnalyticsWindow(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def bounded_window(self):
        if self.end < self.start or (self.end - self.start).days >= 90:
            raise ValueError("Choose an ordered date range of at most 90 days")
        return self
