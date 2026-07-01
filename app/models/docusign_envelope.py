from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DocusignEnvelope(Base):
    """Contrato enviado vía DocuSign desde la plataforma."""

    __tablename__ = "docusign_envelopes"

    id: Mapped[int] = mapped_column(primary_key=True)
    docusign_envelope_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sent_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    signer_name: Mapped[str] = mapped_column(String(255))
    signer_email: Mapped[str] = mapped_column(String(255))
    template_id: Mapped[str] = mapped_column(String(64))
    template_role_name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="sent")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sent_by: Mapped["User"] = relationship(foreign_keys=[sent_by_user_id])  # noqa: F821
    client: Mapped["Client | None"] = relationship(foreign_keys=[client_id])  # noqa: F821
