from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CalendlyConnection(Base):
    __tablename__ = "calendly_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    calendly_user_uri: Mapped[str] = mapped_column(String(255))
    calendly_user_name: Mapped[str] = mapped_column(String(255))
    calendly_user_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scheduling_url: Mapped[str] = mapped_column(String(500))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="calendly_connection")  # noqa: F821
