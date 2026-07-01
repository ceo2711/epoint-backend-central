from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DocusignConnection(Base):
    """Conexión DocuSign a nivel empresa (JWT Grant — una sola cuenta)."""

    __tablename__ = "docusign_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_key: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[str] = mapped_column(String(64))
    impersonated_user_id: Mapped[str] = mapped_column(String(64))
    impersonated_user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_uri: Mapped[str] = mapped_column(String(255))
    auth_server: Mapped[str] = mapped_column(String(120), default="account-d.docusign.com")
    private_key_encrypted: Mapped[str] = mapped_column(Text)
    default_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_template_role_name: Mapped[str] = mapped_column(String(120), default="Signer")
    connected_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    connected_by: Mapped["User | None"] = relationship(foreign_keys=[connected_by_user_id])  # noqa: F821
