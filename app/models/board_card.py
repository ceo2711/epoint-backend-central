from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.board_list import BoardList
    from app.models.card_attachment import CardAttachment
    from app.models.card_comment import CardComment
    from app.models.credential_submission import CredentialSubmission


class BoardCard(Base):
    __tablename__ = "board_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("board_lists.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_links: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDIENTE")
    label: Mapped[str | None] = mapped_column(String(30), nullable=True, default="PENDIENTE")
    position: Mapped[int] = mapped_column(Integer, default=0)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_file_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    client_result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    board_list: Mapped["BoardList"] = relationship(back_populates="cards")
    comments: Mapped[List["CardComment"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    attachments: Mapped[List["CardAttachment"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    credential_submissions: Mapped[List["CredentialSubmission"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
