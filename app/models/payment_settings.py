from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class PaymentSettings(Base):
    """Preferencias de pagos (credenciales viven en variables de entorno)."""

    __tablename__ = "payment_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_provider: Mapped[str] = mapped_column(String(20), default="stripe")
    payments_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    updated_by: Mapped["User | None"] = relationship(foreign_keys=[updated_by_user_id])
