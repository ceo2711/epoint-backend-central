from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.board_card import BoardCard
    from app.models.card_comment import CardComment
    from app.models.user import User


class CardAttachment(Base):
    __tablename__ = "card_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("board_cards.id", ondelete="CASCADE"), index=True)
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_comments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(30))  # TUTORIAL | CLIENT_UPLOAD | SCREENSHOT
    storage_key: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    card: Mapped["BoardCard"] = relationship(back_populates="attachments")
    comment: Mapped["CardComment | None"] = relationship()
    uploaded_by: Mapped["User"] = relationship()
