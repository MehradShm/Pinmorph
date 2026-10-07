import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class Signup(Credentials):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A name is required")
        return value.strip()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str | None
    is_moderator: bool = False
    display_name: str


class BoardInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_secret: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A board name is required")
        return value.strip()


class PinMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    source_url: HttpUrl | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A title is required")
        return value.strip()


class PinOut(BaseModel):
    id: str
    title: str
    description: str
    source_url: str | None
    owner_id: str | None
    provenance: str
    status: str
    processing_error: str | None
    width: int | None
    height: int | None
    dominant_color: str | None
    image_url: str | None
    thumbnail_url: str | None
    created_at: datetime


class PinPage(BaseModel):
    items: list[PinOut]
    next_cursor: str | None
    request_id: str
