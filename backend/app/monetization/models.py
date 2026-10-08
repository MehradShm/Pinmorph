from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PinProduct(Base):
    __tablename__ = "pin_products"
    __table_args__ = (
        CheckConstraint("price > 0", name="positive_price"),
        CheckConstraint(
            "currency IN ('USD', 'CAD', 'EUR', 'GBP', 'AUD', 'NZD', 'SEK', 'DKK')",
            name="supported_currency",
        ),
        CheckConstraint(
            "availability IN ('in_stock', 'out_of_stock', 'preorder', 'discontinued')",
            name="supported_availability",
        ),
    )
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    availability: Mapped[str] = mapped_column(String(20))
    merchant_url: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PinDailyRollup(Base):
    __tablename__ = "pin_daily_rollups"
    __table_args__ = (
        CheckConstraint("traffic IN ('app', 'simulator')", name="valid_traffic"),
        CheckConstraint(
            "served >= 0 AND impressions >= 0 AND closeups >= 0 "
            "AND saves >= 0 AND outbound_clicks >= 0",
            name="nonnegative_counts",
        ),
    )
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    traffic: Mapped[str] = mapped_column(String(12), primary_key=True)
    served: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    closeups: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    outbound_clicks: Mapped[int] = mapped_column(Integer, default=0)
    receipt_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    version: Mapped[str] = mapped_column(String(80))
