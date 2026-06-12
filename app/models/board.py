from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.board_card import BoardCard
    from app.models.board_list import BoardList
    from app.models.client import Client


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), unique=True, index=True)
    template_code: Mapped[str] = mapped_column(String(50), default="DEFAULT_ONBOARDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    client: Mapped["Client"] = relationship(back_populates="board")
    lists: Mapped[List["BoardList"]] = relationship(
        back_populates="board", cascade="all, delete-orphan", order_by="BoardList.position"
    )


class BoardTemplate(Base):
    __tablename__ = "board_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    template_lists: Mapped[List["BoardTemplateList"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class BoardTemplateList(Base):
    __tablename__ = "board_template_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("board_templates.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(150))
    position: Mapped[int] = mapped_column(default=0)

    template: Mapped["BoardTemplate"] = relationship(back_populates="template_lists")
    template_cards: Mapped[List["BoardTemplateCard"]] = relationship(
        back_populates="template_list", cascade="all, delete-orphan"
    )


class BoardTemplateCard(Base):
    __tablename__ = "board_template_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_list_id: Mapped[int] = mapped_column(ForeignKey("board_template_lists.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str | None] = mapped_column(String, nullable=True)
    instructions_md: Mapped[str | None] = mapped_column(String, nullable=True)
    external_links: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON string
    position: Mapped[int] = mapped_column(default=0)
    requires_credentials: Mapped[bool] = mapped_column(default=False)
    requires_file_upload: Mapped[bool] = mapped_column(default=False)

    template_list: Mapped["BoardTemplateList"] = relationship(back_populates="template_cards")
