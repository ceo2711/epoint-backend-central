"""Alta y merge de productos (CREDIT / COURSE / MENTORSHIP) sobre un mismo cliente."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.constants.default_board_cards import EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL
from app.core.encryption import encrypt_value
from app.models.catalog_product import CatalogProduct
from app.models.client import Client
from app.models.client_entitlement import ClientEntitlement
from app.models.enums import ClientStatus, EDUCATION_PRODUCT_CODES, ProductCode
from app.models.merchant import Merchant
from app.models.payment_link import PaymentLink
from app.models.role import Role
from app.models.user import User
from app.schemas.entitlements import EntitlementsResponse, entitlements_from_codes
from app.services.clients import ClientService, _generate_temp_password

logger = logging.getLogger(__name__)

LANDING_SOURCE = "LANDING"
EDUCATION_MERCHANT_CODE = "epoint-credits"


class EntitlementService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def codes_for_client(self, client_id: int) -> set[str]:
        rows = self.db.execute(
            select(ClientEntitlement.product_code).where(ClientEntitlement.client_id == client_id)
        ).scalars().all()
        return {str(code) for code in rows}

    def entitlements_for_client(self, client_id: int | None) -> EntitlementsResponse:
        if not client_id:
            return EntitlementsResponse()
        return entitlements_from_codes(self.codes_for_client(client_id))

    def grant(
        self,
        client: Client,
        product_code: str,
        *,
        payment_link_id: int | None = None,
    ) -> bool:
        """True si se creó el entitlement; False si ya lo tenía."""
        code = product_code.strip().upper()
        existing = self.db.execute(
            select(ClientEntitlement).where(
                ClientEntitlement.client_id == client.id,
                ClientEntitlement.product_code == code,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        self.db.add(
            ClientEntitlement(
                client_id=client.id,
                product_code=code,
                payment_link_id=payment_link_id,
                granted_at=datetime.now(timezone.utc),
            )
        )
        self.db.flush()
        return True

    def get_active_product(self, code: str) -> CatalogProduct:
        product = self.db.execute(
            select(CatalogProduct).where(
                CatalogProduct.code == code.strip().upper(),
                CatalogProduct.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Producto no disponible")
        return product

    def education_merchant(self) -> Merchant:
        merchant = self.db.execute(
            select(Merchant).where(Merchant.code == EDUCATION_MERCHANT_CODE, Merchant.is_active.is_(True))
        ).scalar_one_or_none()
        if merchant is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Comercio epoint-credits no está configurado",
            )
        return merchant

    def system_actor(self) -> User:
        user = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role))
                .where(User.email == EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL)
            )
            .unique()
            .scalar_one_or_none()
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Usuario de sistema no está configurado",
            )
        return user

    def find_client_by_email(self, email: str) -> Client | None:
        return self.db.execute(
            select(Client).where(Client.email == email.strip().lower()).order_by(Client.id).limit(1)
        ).scalar_one_or_none()

    def ensure_credit_track(self, client: Client) -> None:
        """Si el cliente solo tenía productos educativos, arranca onboarding de asesoría."""
        self.grant(client, ProductCode.CREDIT.value)
        if client.status == ClientStatus.SIN_ASESORIA.value:
            client.status = ClientStatus.EN_CARGA_DATOS.value

    def fulfill_education_payment(self, link: PaymentLink) -> Client:
        code = (link.product_code or "").strip().upper()
        if code not in EDUCATION_PRODUCT_CODES:
            raise HTTPException(status_code=400, detail="El link no corresponde a un producto educativo")

        client = None
        if link.client_id:
            client = self.db.get(Client, link.client_id)
        if client is None:
            client = self.find_client_by_email(link.customer_email)

        send_welcome = False
        temp_password: str | None = None
        if client is None:
            client, temp_password = self._create_education_client(link)
            send_welcome = True

        self.grant(client, code, payment_link_id=link.id)
        link.client_id = client.id
        if link.client_registered_at is None:
            link.client_registered_at = datetime.now(timezone.utc)
        self.db.flush()

        if send_welcome and temp_password:
            ClientService(self.db)._send_client_portal_welcome(client, temp_password)
        return client

    def _create_education_client(self, link: PaymentLink) -> tuple[Client, str]:
        actor = self.system_actor()
        merchant = self.education_merchant()
        client_service = ClientService(self.db)
        existing = client_service.find_client_with_email(link.customer_email)
        if existing is not None:
            return existing, ""

        client = Client(
            first_name=link.customer_first_name.strip(),
            last_name=link.customer_last_name.strip(),
            email=link.customer_email.strip().lower(),
            phone=link.customer_phone.strip(),
            source=LANDING_SOURCE,
            merchant_id=merchant.id,
            sede_id=merchant.sede_id,
            registered_by_user_id=actor.id,
            status=ClientStatus.SIN_ASESORIA.value,
            is_qualified=True,
        )
        self.db.add(client)
        self.db.flush()

        temp_password = _generate_temp_password()
        client_role = self.db.execute(select(Role).where(Role.code == "CLIENT")).scalar_one()
        client_service._resolve_portal_user(client, client_role, temp_password)
        client.portal_temp_password_encrypted = encrypt_value(temp_password)
        self.db.flush()
        return client, temp_password
