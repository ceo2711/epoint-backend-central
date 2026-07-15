from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ProspectHistoryEventType


class ProspectHistory(Base):
    __tablename__ = "prospect_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(
        String(40),
        default=ProspectHistoryEventType.STATUS_CHANGE.value,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prospect: Mapped["Prospect"] = relationship(back_populates="history")  # noqa: F821
    changed_by: Mapped["User"] = relationship()  # noqa: F821
