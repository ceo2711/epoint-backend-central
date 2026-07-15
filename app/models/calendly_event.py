from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CalendlyEvent(Base):
    __tablename__ = "calendly_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    calendly_event_uri: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="active")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_type_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invitee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invitee_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invitee_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prospect_id: Mapped[int | None] = mapped_column(
        ForeignKey("prospects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="calendly_events")  # noqa: F821
    prospect: Mapped["Prospect | None"] = relationship(foreign_keys=[prospect_id])  # noqa: F821
