from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

EMAIL_DIRECTION_OUTBOUND = "OUTBOUND"
EMAIL_DIRECTION_INBOUND = "INBOUND"


class SentEmail(Base):
    """Hilo de emails con prospectos o clientes (salientes e inbound)."""

    __tablename__ = "sent_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int | None] = mapped_column(
        ForeignKey("prospects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255))
    from_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255))
    message_html: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(16), default=EMAIL_DIRECTION_OUTBOUND, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resend_email_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    sent_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sent_by: Mapped["User | None"] = relationship()  # noqa: F821
