"""Small independent product modules; all ownership enforced in their services."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import new_id, utcnow


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    interests: Mapped[list] = mapped_column(JSON, default=list)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    email_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reaction(Base):
    __tablename__ = "reactions"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HiddenPin(Base):
    __tablename__ = "hidden_pins"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SafetyReport(Base):
    __tablename__ = "safety_reports"
    __table_args__ = (UniqueConstraint("user_id", "pin_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(40), default="user")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    action: Mapped[str | None] = mapped_column(String(30))
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (UniqueConstraint("user_id", "period"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(20))
    recipient: Mapped[str] = mapped_column(String(254))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
