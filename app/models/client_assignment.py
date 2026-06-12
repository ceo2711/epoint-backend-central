from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.user import User


class ClientAssignment(Base):
    __tablename__ = "client_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    advisor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="assignments")
    advisor: Mapped["User"] = relationship(foreign_keys=[advisor_user_id])
    assigned_by: Mapped["User"] = relationship(foreign_keys=[assigned_by_user_id])
