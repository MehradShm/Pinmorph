import base64
import binascii
import hashlib
import json
import re
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Pin, User
from app.social.policy import visible_owner


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    q: str = Field(min_length=2, max_length=200)
    owner_id: str | None = Field(default=None, min_length=36, max_length=36)
    provenance: Literal["manual_upload", "synthetic_demo", "hm"] | None = None
    created_after: AwareDatetime | None = None
    created_before: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_query(self):
        normalized = " ".join(self.q.lower().split())
        if len(normalized) < 2 or not any(character.isalnum() for character in normalized):
            raise ValueError("Enter at least two characters with a word or number")
        object.__setattr__(self, "q", normalized)
        if self.owner_id:
            UUID(self.owner_id)
        if self.created_after and self.created_before and self.created_after > self.created_before:
            raise ValueError("The start date must precede the end date")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class SearchBackend(Protocol):
    version: str

    def search(
        self,
        db: Session,
        query: SearchQuery,
        viewer: User | None,
        as_of: datetime,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Pin], str | None]: ...


def encode_cursor(query: SearchQuery, pin: Pin) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(
            [
                "search:v1",
                query.fingerprint(),
                pin.created_at.isoformat(),
                pin.id,
            ]
        ).encode()
    ).decode()


def decode_cursor(value: str, query: SearchQuery) -> tuple[datetime, str]:
    try:
        version, fingerprint, raw_time, pin_id = json.loads(
            base64.b64decode(value, altchars=b"-_", validate=True)
        )
        timestamp = datetime.fromisoformat(raw_time)
        UUID(pin_id)
        if (
            version != "search:v1"
            or fingerprint != query.fingerprint()
            or timestamp.utcoffset() is None
        ):
            raise ValueError
        return timestamp, pin_id
    except (ValueError, TypeError, AttributeError, binascii.Error, UnicodeError) as exc:
        raise ValueError("Invalid cursor for this search") from exc


def eligible(query: SearchQuery, viewer: User | None, as_of: datetime):
    statement = select(Pin).where(
        Pin.status == "ready",
        Pin.available_at <= as_of,
        visible_owner(Pin.owner_id, viewer, include_muted=True),
    )
    if query.owner_id:
        statement = statement.where(Pin.owner_id == query.owner_id)
    if query.provenance:
        statement = statement.where(Pin.provenance == query.provenance)
    if query.created_after:
        statement = statement.where(Pin.created_at >= query.created_after)
    if query.created_before:
        statement = statement.where(Pin.created_at <= query.created_before)
    return statement


class PostgresTextSearch:
    # This first catalog search orders matches by recency; learned relevance is a later experiment.
    version = "search:postgres-fts-recency:v1"

    def search(self, db, query, viewer, as_of, limit, cursor):
        statement = eligible(query, viewer, as_of).where(
            Pin.search_document.op("@@")(func.plainto_tsquery("english", query.q))
        )
        if cursor:
            timestamp, pin_id = decode_cursor(cursor, query)
            statement = statement.where(
                or_(
                    Pin.created_at < timestamp,
                    and_(Pin.created_at == timestamp, Pin.id < pin_id),
                )
            )
        pins = list(
            db.scalars(statement.order_by(Pin.created_at.desc(), Pin.id.desc()).limit(limit + 1))
        )
        next_cursor = encode_cursor(query, pins[limit - 1]) if len(pins) > limit else None
        return pins[:limit], next_cursor

    def suggest(self, db, query, viewer, as_of, limit):
        # User text never becomes SQL or unvalidated tsquery syntax.
        tokens = re.findall(r"[a-z0-9]+", query.q)[:8]
        if not tokens:
            return []
        expression = " & ".join([*tokens[:-1], f"{tokens[-1]}:*"])
        statement = (
            eligible(query, viewer, as_of)
            .with_only_columns(Pin.title)
            .where(Pin.search_document.op("@@")(func.to_tsquery("english", expression)))
            .distinct()
            .order_by(Pin.title)
            .limit(limit)
        )
        return list(db.scalars(statement))
