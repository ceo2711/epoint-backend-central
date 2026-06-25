from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.card_attachment import CardAttachment


class CardAttachmentVerification(Base):
    __tablename__ = "card_attachment_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    attachment_id: Mapped[int] = mapped_column(
        ForeignKey("card_attachments.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    ai_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    rejection_reasons: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    approval_reasons: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    attachment: Mapped["CardAttachment"] = relationship(back_populates="verifications")
