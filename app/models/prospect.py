from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ProspectStatus

if TYPE_CHECKING:
    from app.models.calendly_event import CalendlyEvent
    from app.models.client import Client
    from app.models.docusign_envelope import DocusignEnvelope
    from app.models.influencer import Influencer
    from app.models.merchant import Merchant
    from app.models.payment_link import PaymentLink
    from app.models.prospect_history import ProspectHistory
    from app.models.sede import Sede
    from app.models.user import User


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"), index=True)
    assigned_to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(40),
        default=ProspectStatus.PENDIENTE_CONTACTAR.value,
        index=True,
    )
    is_qualified: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(30))
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    converted_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    calendly_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendly_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    docusign_envelope_id: Mapped[int | None] = mapped_column(
        ForeignKey("docusign_envelopes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    merchant: Mapped["Merchant"] = relationship()
    sede: Mapped["Sede"] = relationship(back_populates="prospects")
    assigned_to: Mapped["User"] = relationship(foreign_keys=[assigned_to_user_id])
    influencer: Mapped["Influencer | None"] = relationship(foreign_keys=[influencer_id])
    converted_client: Mapped["Client | None"] = relationship(foreign_keys=[converted_client_id])
    calendly_event: Mapped["CalendlyEvent | None"] = relationship(foreign_keys=[calendly_event_id])
    docusign_envelope: Mapped["DocusignEnvelope | None"] = relationship(foreign_keys=[docusign_envelope_id])
    payment_link: Mapped["PaymentLink | None"] = relationship(foreign_keys=[payment_link_id])
    history: Mapped[List["ProspectHistory"]] = relationship(
        back_populates="prospect",
        cascade="all, delete-orphan",
        order_by="ProspectHistory.created_at.desc()",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
