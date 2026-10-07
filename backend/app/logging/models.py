"""Schema scaffolding: constraints support, but do not replace, ingestion validation."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FeedRequest(Base):
    __tablename__ = "feed_requests"
    __table_args__ = (
        UniqueConstraint("request_id", "user_id"),
        CheckConstraint("latency_ms >= 0", name="nonnegative_latency"),
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    surface: Mapped[str] = mapped_column(String(30))
    context: Mapped[dict] = mapped_column(JSON)
    experiment_arms: Mapped[dict] = mapped_column(JSON)
    model_versions: Mapped[dict] = mapped_column(JSON)
    config_version: Mapped[str] = mapped_column(String(100))
    latency_ms: Mapped[float] = mapped_column(Float)
    served_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sim_run_id: Mapped[str | None] = mapped_column(String(36), index=True)


class ServedItem(Base):
    __tablename__ = "served_items"
    __table_args__ = (
        UniqueConstraint("request_id", "position", name="uq_served_items_request_position"),
        UniqueConstraint(
            "request_id", "pin_id", "position", name="uq_served_items_request_pin_position"
        ),
        CheckConstraint("position >= 0", name="nonnegative_position"),
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("feed_requests.request_id", ondelete="CASCADE"), primary_key=True
    )
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    candidate_sources: Mapped[list] = mapped_column(JSON)
    retrieval_score: Mapped[float | None] = mapped_column(Float)
    rank_score: Mapped[float] = mapped_column(Float)
    final_score: Mapped[float] = mapped_column(Float)


class ServedFeature(Base):
    __tablename__ = "served_features"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "pin_id"],
            ["served_items.request_id", "served_items.pin_id"],
            ondelete="CASCADE",
        ),
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pin_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    features: Mapped[dict] = mapped_column(JSON)
    feature_schema_version: Mapped[str] = mapped_column(String(100))
    feature_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventReceipt(Base):
    """One global key across event kinds; normalized content makes conflicts detectable."""

    __tablename__ = "event_receipts"
    __table_args__ = (CheckConstraint("kind IN ('impression', 'engagement')", name="valid_kind"),)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(30))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    client_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sim_run_id: Mapped[str | None] = mapped_column(String(36), index=True)


class Impression(Base):
    __tablename__ = "impressions"
    __table_args__ = (
        UniqueConstraint("request_id", "pin_id"),
        ForeignKeyConstraint(
            ["request_id", "pin_id", "position"],
            ["served_items.request_id", "served_items.pin_id", "served_items.position"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["request_id", "user_id"],
            ["feed_requests.request_id", "feed_requests.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("position >= 0", name="nonnegative_position"),
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_receipts.event_id", ondelete="CASCADE"), primary_key=True
    )
    request_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[str] = mapped_column(String(36))
    pin_id: Mapped[str] = mapped_column(String(36))
    position: Mapped[int] = mapped_column(Integer)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    view_rule_version: Mapped[str] = mapped_column(String(80))
    sim_run_id: Mapped[str | None] = mapped_column(String(36), index=True)


class Engagement(Base):
    __tablename__ = "engagements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "pin_id", "position"],
            ["served_items.request_id", "served_items.pin_id", "served_items.position"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["request_id", "user_id"],
            ["feed_requests.request_id", "feed_requests.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(request_id IS NULL AND position IS NULL) OR "
            "(request_id IS NOT NULL AND position IS NOT NULL AND position >= 0)",
            name="complete_attribution",
        ),
        CheckConstraint("type IN ('closeup', 'save', 'outbound_click')", name="supported_action"),
        CheckConstraint(
            "attribution_status IN ('pending', 'attributed', 'unattributed')",
            name="valid_attribution_status",
        ),
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_receipts.event_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str | None] = mapped_column(String(36))
    position: Mapped[int | None] = mapped_column(Integer)
    # The requested ID can arrive later; only the resolved ID is a foreign key.
    referenced_impression_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    impression_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("impressions.event_id", ondelete="SET NULL"), index=True
    )
    attribution_status: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(30))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sim_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
