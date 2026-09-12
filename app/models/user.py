from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.area import Area
    from app.models.calendly_connection import CalendlyConnection
    from app.models.calendly_event import CalendlyEvent
    from app.models.merchant import Merchant
    from app.models.notification import Notification
    from app.models.role import Role
    from app.models.sede import Sede
    from app.models.session import UserSession


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    avatar_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    active_merchant_id: Mapped[int | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sede_id: Mapped[int | None] = mapped_column(
        ForeignKey("sedes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Jerarquía de vendedores: un sub-vendedor apunta a su vendedor padre (un solo nivel).
    parent_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    first_steps_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped["Role"] = relationship(back_populates="users")
    area: Mapped["Area | None"] = relationship(back_populates="users")
    sede: Mapped["Sede | None"] = relationship(back_populates="users")
    active_merchant: Mapped["Merchant | None"] = relationship(foreign_keys=[active_merchant_id])
    parent: Mapped["User | None"] = relationship(
        "User",
        remote_side="User.id",
        foreign_keys=[parent_user_id],
        back_populates="sub_sellers",
    )
    sub_sellers: Mapped[List["User"]] = relationship(
        "User",
        foreign_keys=[parent_user_id],
        back_populates="parent",
    )
    sessions: Mapped[List["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    calendly_connection: Mapped["CalendlyConnection | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    calendly_events: Mapped[List["CalendlyEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
