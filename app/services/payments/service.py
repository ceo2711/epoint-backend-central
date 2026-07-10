"""Lógica de links de pago (Stripe / Authorize.net)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models.client import Client
from app.models.enums import ClientSource
from app.models.payment_link import PaymentLink, PaymentLinkStatus, PaymentProvider
from app.models.user import User
from app.schemas.payment import (
    PaymentConfigResponse,
    PaymentLinkCreate,
    PaymentLinkResponse,
    PaymentProviderStatus,
    PaymentRegisterClientRequest,
    PublicPaymentLinkResponse,
)
from app.services.clients import ClientService
from app.services.notifications.service import NotificationService
from app.services.payments.authorize_provider import AuthorizePaymentProvider
from app.services.payments.stripe_provider import StripePaymentProvider

logger = logging.getLogger(__name__)

PAYMENT_ROLES = frozenset({"ADMIN", "SALES_REP"})


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.stripe = StripePaymentProvider(self.settings)
        self.authorize = AuthorizePaymentProvider(self.settings)

    @staticmethod
    def ensure_access(user: User) -> None:
        if user.role.code not in PAYMENT_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    @property
    def stub_mode(self) -> bool:
        return not (self.stripe.is_configured or self.authorize.is_configured)

    def get_config(self, user: User) -> PaymentConfigResponse:
        self.ensure_access(user)
        providers = [
            PaymentProviderStatus(provider="stripe", configured=self.stripe.is_configured, label="Stripe"),
            PaymentProviderStatus(
                provider="authorize",
                configured=self.authorize.is_configured,
                label="Authorize.net",
            ),
        ]
        return PaymentConfigResponse(
            payments_enabled=self.settings.payments_enabled,
            default_provider=self.settings.payments_default_provider_normalized,  # type: ignore[arg-type]
            stub_mode=self.stub_mode,
            providers=providers,
        )

    def _to_response(self, link: PaymentLink) -> PaymentLinkResponse:
        created_by_name = None
        if link.created_by:
            created_by_name = f"{link.created_by.first_name} {link.created_by.last_name}".strip()
        return PaymentLinkResponse(
            id=link.id,
            public_token=link.public_token,
            created_by_user_id=link.created_by_user_id,
            client_id=link.client_id,
            customer_first_name=link.customer_first_name,
            customer_last_name=link.customer_last_name,
            customer_email=link.customer_email,
            customer_phone=link.customer_phone,
            amount=link.amount,
            currency=link.currency,
            provider=link.provider,
            status=link.status,
            description=link.description,
            payment_url=link.payment_url,
            external_checkout_url=link.external_checkout_url,
            paid_at=link.paid_at,
            client_registered_at=link.client_registered_at,
            created_at=link.created_at,
            created_by_name=created_by_name,
        )

    def list_links(self, user: User, *, created_by_user_id: int | None = None) -> list[PaymentLinkResponse]:
        self.ensure_access(user)
        stmt = select(PaymentLink).options(joinedload(PaymentLink.created_by)).order_by(PaymentLink.created_at.desc())
        if user.role.code == "SALES_REP":
            stmt = stmt.where(PaymentLink.created_by_user_id == user.id)
        elif created_by_user_id is not None:
            stmt = stmt.where(PaymentLink.created_by_user_id == created_by_user_id)
        rows = self.db.execute(stmt).unique().scalars().all()
        return [self._to_response(row) for row in rows]

    def create_link(self, user: User, payload: PaymentLinkCreate) -> PaymentLinkResponse:
        self.ensure_access(user)
        if not self.settings.payments_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Los pagos están deshabilitados")

        token = uuid.uuid4().hex
        payment_url = f"{self.settings.portal_base_url}/pagar/{token}"
        cancel_url = payment_url
        success_url = f"{payment_url}?paid=1"

        external_id: str | None = None
        external_url: str | None = None

        if payload.provider == PaymentProvider.STRIPE.value and self.stripe.is_configured:
            try:
                external_id, external_url = self.stripe.create_checkout_link(
                    amount=payload.amount,
                    currency=payload.currency,
                    customer_email=str(payload.customer_email),
                    description=payload.description,
                    success_url=success_url,
                    cancel_url=cancel_url,
                )
            except NotImplementedError:
                logger.info("Stripe configurado pero integración pendiente; usando stub local")
        elif payload.provider == PaymentProvider.AUTHORIZE.value and self.authorize.is_configured:
            try:
                external_id, external_url = self.authorize.create_checkout_link(
                    amount=payload.amount,
                    currency=payload.currency,
                    customer_email=str(payload.customer_email),
                    description=payload.description,
                    return_url=success_url,
                    cancel_url=cancel_url,
                )
            except NotImplementedError:
                logger.info("Authorize configurado pero integración pendiente; usando stub local")

        link = PaymentLink(
            public_token=token,
            created_by_user_id=user.id,
            customer_first_name=payload.customer_first_name.strip(),
            customer_last_name=payload.customer_last_name.strip(),
            customer_email=str(payload.customer_email).strip().lower(),
            customer_phone=payload.customer_phone.strip(),
            amount=payload.amount,
            currency=payload.currency.upper(),
            provider=payload.provider,
            status=PaymentLinkStatus.PENDING.value,
            description=payload.description,
            payment_url=external_url or payment_url,
            external_checkout_id=external_id,
            external_checkout_url=external_url,
        )
        self.db.add(link)
        self.db.commit()
        self.db.refresh(link)
        return self._to_response(link)

    def cancel_link(self, user: User, link_id: int) -> PaymentLinkResponse:
        self.ensure_access(user)
        link = self._get_link_for_user(user, link_id)
        if link.status != PaymentLinkStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Solo se pueden cancelar links pendientes")
        link.status = PaymentLinkStatus.CANCELLED.value
        self.db.commit()
        self.db.refresh(link)
        return self._to_response(link)

    def get_public_link(self, token: str) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        can_pay = link.status == PaymentLinkStatus.PENDING.value and self.settings.payments_enabled
        return PublicPaymentLinkResponse(
            customer_first_name=link.customer_first_name,
            customer_last_name=link.customer_last_name,
            customer_email=link.customer_email,
            amount=link.amount,
            currency=link.currency,
            provider=link.provider,
            status=link.status,
            description=link.description,
            stub_mode=self.stub_mode,
            can_pay=can_pay,
        )

    def complete_public_payment(self, token: str) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        if link.status != PaymentLinkStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Este link ya no está disponible para pago")
        if not self.stub_mode:
            raise HTTPException(
                status_code=400,
                detail="El pago debe completarse en el checkout del proveedor",
            )
        self._mark_paid(link)
        self.db.commit()
        return self.get_public_link(token)

    def register_client_from_link(
        self,
        user: User,
        link_id: int,
        payload: PaymentRegisterClientRequest,
    ) -> tuple[int, str]:
        self.ensure_access(user)
        link = self._get_link_for_user(user, link_id)
        if link.status != PaymentLinkStatus.PAID.value:
            raise HTTPException(status_code=400, detail="El pago debe estar completado antes de registrar al cliente")
        if link.client_id is not None:
            raise HTTPException(status_code=400, detail="Este pago ya tiene un cliente registrado")

        try:
            source = ClientSource(payload.source).value
        except ValueError:
            source = ClientSource.OTHER.value

        client_service = ClientService(self.db)
        client = client_service.create_client(
            actor=user,
            first_name=link.customer_first_name,
            last_name=link.customer_last_name,
            email=link.customer_email,
            phone=link.customer_phone,
            source=source,
            merchant_id=payload.merchant_id,
        )
        link.client_id = client.id
        link.client_registered_at = datetime.now(timezone.utc)
        self.db.commit()
        return client.id, "Cliente registrado correctamente"

    def _mark_paid(self, link: PaymentLink) -> None:
        link.status = PaymentLinkStatus.PAID.value
        link.paid_at = datetime.now(timezone.utc)
        creator = self.db.get(User, link.created_by_user_id)
        if creator and creator.is_active:
            NotificationService(self.db).notify(
                event_type="PAYMENT_LINK_COMPLETED",
                users=[creator],
                title="Pago recibido",
                body=(
                    f"{link.customer_first_name} {link.customer_last_name} completó el pago de "
                    f"{link.currency} {link.amount}."
                ),
                payload={
                    "payment_link_id": link.id,
                    "customer_email": link.customer_email,
                    "customer_name": f"{link.customer_first_name} {link.customer_last_name}",
                    "amount": str(link.amount),
                    "currency": link.currency,
                },
                commit=False,
            )

    def _get_link_by_token(self, token: str) -> PaymentLink:
        link = self.db.execute(
            select(PaymentLink).where(PaymentLink.public_token == token)
        ).scalar_one_or_none()
        if link is None:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        return link

    def _get_link_for_user(self, user: User, link_id: int) -> PaymentLink:
        link = self.db.execute(
            select(PaymentLink)
            .options(joinedload(PaymentLink.created_by))
            .where(PaymentLink.id == link_id)
        ).unique().scalar_one_or_none()
        if link is None:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        if user.role.code == "SALES_REP" and link.created_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        return link
