"""Product records. Imported purchases deliberately live outside app saves/events."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.monetization.models import PinProduct


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80))
    is_moderator: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_business: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    business_name: Mapped[str | None] = mapped_column(String(120))
    business_website: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str] = mapped_column(String(500), default="", server_default="")
    source_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(40))
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Pin(Base):
    __tablename__ = "pins"
    __table_args__ = (
        Index("ix_pins_search_document", "search_document", postgresql_using="gin"),
        UniqueConstraint("owner_id", "pixel_hash", name="uq_pins_owner_pixel_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product: Mapped[PinProduct | None] = relationship(
        lazy="selectin", passive_deletes=True, cascade="all, delete-orphan"
    )
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    search_document: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english'::regconfig, "
            "coalesce(title, '') || ' ' || coalesce(description, ''))",
            persisted=True,
        ),
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    source_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    import_run_id: Mapped[str | None] = mapped_column(ForeignKey("import_runs.id"))
    provenance: Mapped[str] = mapped_column(String(40), default="manual_upload")
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    pixel_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    original_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # One job at a time; the active job ID also protects against stale retries.
    media_job_id: Mapped[str | None] = mapped_column(String(100))
    processing_error: Mapped[str | None] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    dominant_color: Mapped[str | None] = mapped_column(String(7))
    variants: Mapped[dict] = mapped_column(JSON, default=dict)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Board(Base):
    __tablename__ = "boards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    # Existing boards were owner-only. Publishing one must be an explicit choice.
    is_secret: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BoardSection(Base):
    __tablename__ = "board_sections"
    __table_args__ = (
        UniqueConstraint("board_id", "id", name="uq_board_sections_board_id_id"),
        UniqueConstraint("board_id", "name", name="uq_board_sections_board_id_name"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Save(Base):
    __tablename__ = "saves"
    __table_args__ = (
        UniqueConstraint("board_id", "pin_id"),
        ForeignKeyConstraint(
            ["board_id", "section_id"],
            ["board_sections.board_id", "board_sections.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(
        ForeignKey("board_sections.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportedInteraction(Base):
    __tablename__ = "imported_interactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_key: Mapped[str] = mapped_column(String(200), unique=True)
    import_run_id: Mapped[str] = mapped_column(ForeignKey("import_runs.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    original_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    label_provenance: Mapped[str] = mapped_column(String(40), default="imported_purchase_proxy")
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
