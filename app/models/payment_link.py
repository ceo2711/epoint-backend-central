import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.user import User


class PaymentProvider(str, enum.Enum):
    STRIPE = "stripe"
    AUTHORIZE = "authorize"
    PAYPAL = "paypal"


class PaymentLinkStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaymentLink(Base):
    __tablename__ = "payment_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: uuid.uuid4().hex)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    prospect_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id", ondelete="SET NULL"), nullable=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_first_name: Mapped[str] = mapped_column(String(100))
    customer_last_name: Mapped[str] = mapped_column(String(100))
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    customer_phone: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    pending_charge_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    allow_partial: Mapped[bool] = mapped_column(Boolean, default=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=PaymentLinkStatus.PENDING.value, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_url: Mapped[str] = mapped_column(Text)
    external_checkout_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_payment_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remainder_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    client_registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    created_by: Mapped["User"] = relationship(foreign_keys=[created_by_user_id])
    client: Mapped["Client | None"] = relationship(foreign_keys=[client_id])
