"""Lógica de links de pago (Authorize.net / PayPal)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models.client import Client
from app.models.enums import ClientSource
from app.models.merchant import Merchant
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
from app.services.email.payment_link import PaymentLinkEmailPayload, send_payment_link_email
from app.services.notifications.service import NotificationService
from app.services.payments.authorize_provider import AuthorizePaymentProvider
from app.services.payments.base import PaymentProviderError
from app.services.payments.paypal_provider import PayPalPaymentProvider

logger = logging.getLogger(__name__)

PAYMENT_ROLES = frozenset({"ADMIN", "BRANCH_MANAGER", "SALES_REP"})

PROVIDER_LABELS = {
    PaymentProvider.AUTHORIZE.value: "Authorize.net",
    PaymentProvider.PAYPAL.value: "PayPal",
    PaymentProvider.STRIPE.value: "Stripe",
}

ACTIVE_PROVIDERS = frozenset({PaymentProvider.AUTHORIZE.value, PaymentProvider.PAYPAL.value})


@dataclass(frozen=True, slots=True)
class PaymentLinkCreateResult:
    link: PaymentLinkResponse
    email_sent: bool


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.authorize = AuthorizePaymentProvider(self.settings)
        self.paypal = PayPalPaymentProvider(self.settings)

    @staticmethod
    def ensure_access(user: User) -> None:
        if user.role.code not in PAYMENT_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    @property
    def stub_mode(self) -> bool:
        return not (self.authorize.is_configured or self.paypal.is_configured)

    def get_config(self, user: User) -> PaymentConfigResponse:
        self.ensure_access(user)
        providers = [
            PaymentProviderStatus(
                provider="authorize",
                configured=self.authorize.is_configured,
                label="Authorize.net",
            ),
            PaymentProviderStatus(
                provider="paypal",
                configured=self.paypal.is_configured,
                label="PayPal",
            ),
        ]
        default = self.settings.payments_default_provider_normalized
        if default not in ACTIVE_PROVIDERS:
            default = PaymentProvider.AUTHORIZE.value
        return PaymentConfigResponse(
            payments_enabled=self.settings.payments_enabled,
            default_provider=default,  # type: ignore[arg-type]
            stub_mode=self.stub_mode,
            providers=providers,
            webhook_base_url=self.settings.payments_webhook_base_url,
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
            prospect_id=link.prospect_id,
            customer_first_name=link.customer_first_name,
            customer_last_name=link.customer_last_name,
            customer_email=link.customer_email,
            customer_phone=link.customer_phone,
            amount=link.amount,
            currency=link.currency,
            provider=link.provider,  # type: ignore[arg-type]
            status=link.status,  # type: ignore[arg-type]
            description=link.description,
            payment_url=link.payment_url,
            external_checkout_url=link.external_checkout_url,
            paid_at=link.paid_at,
            client_registered_at=link.client_registered_at,
            created_at=link.created_at,
            created_by_name=created_by_name,
        )

    def list_links(
        self,
        user: User,
        *,
        merchant_id: int,
        created_by_user_id: int | None = None,
    ) -> list[PaymentLinkResponse]:
        self.ensure_access(user)
        stmt = (
            select(PaymentLink)
            .options(joinedload(PaymentLink.created_by))
            .where(PaymentLink.merchant_id == merchant_id)
            .order_by(PaymentLink.created_at.desc())
        )
        if user.role.code == "SALES_REP":
            stmt = stmt.where(PaymentLink.created_by_user_id == user.id)
        elif created_by_user_id is not None:
            stmt = stmt.where(PaymentLink.created_by_user_id == created_by_user_id)
        rows = self.db.execute(stmt).unique().scalars().all()
        return [self._to_response(row) for row in rows]

    def create_link(
        self, user: User, payload: PaymentLinkCreate, *, merchant_id: int
    ) -> PaymentLinkCreateResult:
        self.ensure_access(user)
        if not self.settings.payments_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Los pagos están deshabilitados")
        if payload.provider not in ACTIVE_PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Proveedor no disponible. Usá Authorize.net o PayPal.",
            )

        token = uuid.uuid4().hex
        portal_url = f"{self.settings.portal_base_url}/pagar/{token}"
        success_url = f"{portal_url}?paid=1"
        cancel_url = portal_url

        external_id: str | None = None
        external_url: str | None = None

        try:
            if payload.provider == PaymentProvider.AUTHORIZE.value and self.authorize.is_configured:
                result = self.authorize.create_checkout_link(
                    amount=payload.amount,
                    currency=payload.currency,
                    customer_email=str(payload.customer_email),
                    description=payload.description,
                    reference_id=token,
                    return_url=success_url,
                    cancel_url=cancel_url,
                )
                external_id = result.external_id
                external_url = result.checkout_url
            elif payload.provider == PaymentProvider.PAYPAL.value and self.paypal.is_configured:
                result = self.paypal.create_checkout_link(
                    amount=payload.amount,
                    currency=payload.currency,
                    customer_email=str(payload.customer_email),
                    description=payload.description,
                    reference_id=token,
                    return_url=success_url,
                    cancel_url=cancel_url,
                )
                external_id = result.external_id
                external_url = result.checkout_url
        except PaymentProviderError as exc:
            logger.warning("Checkout externo falló (%s); usando portal local", exc)
            if not self.stub_mode:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(exc),
                ) from exc

        link = PaymentLink(
            public_token=token,
            created_by_user_id=user.id,
            merchant_id=merchant_id,
            prospect_id=payload.prospect_id,
            customer_first_name=payload.customer_first_name.strip(),
            customer_last_name=payload.customer_last_name.strip(),
            customer_email=str(payload.customer_email).strip().lower(),
            customer_phone=payload.customer_phone.strip(),
            amount=payload.amount,
            currency=payload.currency.upper(),
            provider=payload.provider,
            status=PaymentLinkStatus.PENDING.value,
            description=payload.description,
            payment_url=external_url or portal_url,
            external_checkout_id=external_id,
            external_checkout_url=external_url,
        )
        self.db.add(link)
        self.db.flush()
        if payload.prospect_id is not None:
            from app.services.prospects import ProspectService

            prospect = ProspectService(self.db)._get_prospect_for_user(
                user, payload.prospect_id, merchant_id=merchant_id
            )
            ProspectService(self.db).attach_payment_link(actor=user, prospect=prospect, link=link)
        self.db.commit()
        self.db.refresh(link)

        email_sent = False
        if payload.send_email:
            merchant_name: str | None = None
            if merchant_id:
                merchant_row = self.db.get(Merchant, merchant_id)
                merchant_name = merchant_row.name if merchant_row else None
            email_sent = send_payment_link_email(
                PaymentLinkEmailPayload(
                    recipient_email=link.customer_email,
                    first_name=link.customer_first_name,
                    amount=link.amount,
                    currency=link.currency,
                    payment_url=portal_url,
                    provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
                    payment_link_id=link.id,
                    description=link.description,
                    merchant_name=merchant_name,
                )
            )
            if not email_sent:
                logger.warning(
                    "No se pudo enviar email de pago a %s (link_id=%s)",
                    link.customer_email,
                    link.id,
                )

        return PaymentLinkCreateResult(link=self._to_response(link), email_sent=email_sent)

    def cancel_link(self, user: User, link_id: int, *, merchant_id: int) -> PaymentLinkResponse:
        self.ensure_access(user)
        link = self._get_link_for_user(user, link_id, merchant_id=merchant_id)
        if link.status != PaymentLinkStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Solo se pueden cancelar links pendientes")
        link.status = PaymentLinkStatus.CANCELLED.value
        self.db.commit()
        self.db.refresh(link)
        return self._to_response(link)

    def get_public_link(self, token: str) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        can_pay = link.status == PaymentLinkStatus.PENDING.value and self.settings.payments_enabled
        checkout_url = link.external_checkout_url if not self.stub_mode else None
        return PublicPaymentLinkResponse(
            customer_first_name=link.customer_first_name,
            customer_last_name=link.customer_last_name,
            customer_email=link.customer_email,
            amount=link.amount,
            currency=link.currency,
            provider=link.provider,  # type: ignore[arg-type]
            status=link.status,  # type: ignore[arg-type]
            description=link.description,
            stub_mode=self.stub_mode,
            can_pay=can_pay,
            checkout_url=checkout_url,
            provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
        )

    def complete_public_payment(self, token: str) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        if link.status != PaymentLinkStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Este link ya no está disponible para pago")
        if not self.stub_mode:
            if link.provider == PaymentProvider.PAYPAL.value and link.external_checkout_id:
                self._capture_paypal_if_completed(link)
                self.db.commit()
                return self.get_public_link(token)
            raise HTTPException(
                status_code=400,
                detail="El pago debe completarse en el checkout del proveedor",
            )
        self._mark_paid(link)
        self.db.commit()
        return self.get_public_link(token)

    def confirm_paypal_return(self, token: str, *, order_id: str | None = None) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        if link.provider != PaymentProvider.PAYPAL.value:
            raise HTTPException(status_code=400, detail="Este link no usa PayPal")
        if order_id and link.external_checkout_id and order_id != link.external_checkout_id:
            raise HTTPException(status_code=400, detail="La orden PayPal no coincide con el link")
        self._capture_paypal_if_completed(link)
        self.db.commit()
        return self.get_public_link(token)

    def handle_paypal_webhook(self, payload: dict) -> dict:
        event_type = payload.get("event_type")
        resource = payload.get("resource") or {}
        if event_type == "CHECKOUT.ORDER.APPROVED":
            order_id = str(resource.get("id", ""))
            link = self._get_link_by_external_id(order_id)
            if link:
                self._capture_paypal_if_completed(link)
                self.db.commit()
        elif event_type == "PAYMENT.CAPTURE.COMPLETED":
            custom_id = resource.get("custom_id") or resource.get("invoice_id")
            if custom_id:
                link = self._get_link_by_token(str(custom_id), raise_if_missing=False)
                if link and link.status == PaymentLinkStatus.PENDING.value:
                    self._mark_paid(link)
                    self.db.commit()
        return {"received": True}

    def handle_authorize_webhook(self, payload: dict) -> dict:
        event_type = payload.get("eventType") or payload.get("event_type")
        payload_body = payload.get("payload") or payload
        if event_type in {"net.authorize.payment.authcapture.created", "net.authorize.payment.capture.created"}:
            invoice = (
                payload_body.get("invoiceNumber")
                or payload_body.get("order", {}).get("invoiceNumber")
                or payload_body.get("entityName")
            )
            if invoice:
                link = self._get_link_by_token(str(invoice), raise_if_missing=False)
                if link and link.status == PaymentLinkStatus.PENDING.value:
                    self._mark_paid(link)
                    self.db.commit()
        return {"received": True}

    def register_client_from_link(
        self,
        user: User,
        link_id: int,
        payload: PaymentRegisterClientRequest,
        *,
        merchant_id: int,
    ) -> tuple[int, str]:
        self.ensure_access(user)
        link = self._get_link_for_user(user, link_id, merchant_id=merchant_id)
        if link.status != PaymentLinkStatus.PAID.value:
            raise HTTPException(status_code=400, detail="El pago debe estar completado antes de registrar al cliente")
        if link.client_id is not None:
            raise HTTPException(status_code=400, detail="Este pago ya tiene un cliente registrado")

        try:
            source = ClientSource(payload.source).value
        except ValueError:
            source = ClientSource.OTHER.value

        resolved_merchant_id = payload.merchant_id or link.merchant_id or merchant_id
        client_service = ClientService(self.db)
        client = client_service.create_client(
            actor=user,
            first_name=link.customer_first_name,
            last_name=link.customer_last_name,
            email=link.customer_email,
            phone=link.customer_phone,
            source=source,
            merchant_id=resolved_merchant_id,
        )
        link.client_id = client.id
        link.client_registered_at = datetime.now(timezone.utc)
        self.db.commit()
        return client.id, "Cliente registrado correctamente"

    def _capture_paypal_if_completed(self, link: PaymentLink) -> None:
        if not link.external_checkout_id or not self.paypal.is_configured:
            return
        if link.status != PaymentLinkStatus.PENDING.value:
            return
        try:
            order = self.paypal.get_order(link.external_checkout_id)
            order_status = str(order.get("status", "")).upper()
            if order_status == "COMPLETED":
                self._mark_paid(link)
                return
            if order_status == "APPROVED":
                capture = self.paypal.capture_order(link.external_checkout_id)
                if str(capture.get("status", "")).upper() == "COMPLETED":
                    self._mark_paid(link)
        except PaymentProviderError as exc:
            logger.warning("No se pudo capturar orden PayPal %s: %s", link.external_checkout_id, exc)

    def _mark_paid(self, link: PaymentLink) -> None:
        if link.status == PaymentLinkStatus.PAID.value:
            return
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
                    "prospect_id": link.prospect_id,
                    "customer_email": link.customer_email,
                    "customer_name": f"{link.customer_first_name} {link.customer_last_name}",
                    "amount": str(link.amount),
                    "currency": link.currency,
                },
                commit=False,
            )
        if link.prospect_id is not None:
            from app.services.prospects import ProspectService

            ProspectService(self.db).on_payment_completed(link)

    def _get_link_by_token(self, token: str, *, raise_if_missing: bool = True) -> PaymentLink | None:
        link = self.db.execute(
            select(PaymentLink).where(PaymentLink.public_token == token)
        ).scalar_one_or_none()
        if link is None and raise_if_missing:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        return link

    def _get_link_by_external_id(self, external_id: str) -> PaymentLink | None:
        return self.db.execute(
            select(PaymentLink).where(PaymentLink.external_checkout_id == external_id)
        ).scalar_one_or_none()

    def _get_link_for_user(self, user: User, link_id: int, *, merchant_id: int) -> PaymentLink:
        link = self.db.execute(
            select(PaymentLink)
            .options(joinedload(PaymentLink.created_by))
            .where(PaymentLink.id == link_id)
        ).unique().scalar_one_or_none()
        if link is None or link.merchant_id != merchant_id:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        if user.role.code == "SALES_REP" and link.created_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        return link
