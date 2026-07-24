from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.sede import Sede
    from app.models.user import User


class Influencer(Base):
    """Influencer asociado a una sede; el jefe de área de ventas lo registra y lo vincula a un vendedor."""

    __tablename__ = "influencers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"), index=True)
    sales_rep_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    sede: Mapped["Sede"] = relationship()
    sales_rep: Mapped["User"] = relationship(foreign_keys=[sales_rep_user_id])
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])
