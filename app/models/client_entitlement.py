from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.payment_link import PaymentLink


class ClientEntitlement(Base):
    __tablename__ = "client_entitlements"
    __table_args__ = (UniqueConstraint("client_id", "product_code", name="uq_client_entitlements_client_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    product_code: Mapped[str] = mapped_column(String(40), index=True)
    payment_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    client: Mapped["Client"] = relationship(back_populates="entitlements")
    payment_link: Mapped["PaymentLink | None"] = relationship()
