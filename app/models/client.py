from datetime import date, datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ClientStatus

if TYPE_CHECKING:
    from app.models.address import Address
    from app.models.board import Board
    from app.models.client_assignment import ClientAssignment
    from app.models.document import Document
    from app.models.merchant import Merchant
    from app.models.sede import Sede
    from app.models.user import User
    from app.models.vehicle import Vehicle


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(40), default=ClientStatus.PENDIENTE_DE_REVISION.value, index=True)
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=True)

    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(30))
    source: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("merchants.id"), nullable=True, index=True)
    sede_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sedes.id"), nullable=True, index=True)

    registered_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    docusign_contract_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    docusign_envelope_id: Mapped[int | None] = mapped_column(
        ForeignKey("docusign_envelopes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        unique=True,
    )
    last_onboarding_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_board_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    conversion_welcome_email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ssn_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    portal_temp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    docusign_envelope: Mapped["DocusignEnvelope | None"] = relationship(  # noqa: F821
        foreign_keys=[docusign_envelope_id],
    )
    merchant: Mapped["Merchant | None"] = relationship(back_populates="clients")
    sede: Mapped["Sede | None"] = relationship(back_populates="clients")
    registered_by: Mapped["User"] = relationship(foreign_keys=[registered_by_user_id])
    approved_by: Mapped["User | None"] = relationship(foreign_keys=[approved_by_user_id])
    assignments: Mapped[List["ClientAssignment"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    addresses: Mapped[List["Address"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    vehicles: Mapped[List["Vehicle"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    board: Mapped["Board | None"] = relationship(
        back_populates="client",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
