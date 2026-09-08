"""Lógica de links de pago (Authorize.net / PayPal)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
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
from app.services.payments.amounts import (
    STANDARD_INITIAL_PAYMENT,
    is_open_payment,
    is_payment_satisfied,
    remaining_amount,
    remaining_to_standard,
)
from app.services.clients import ClientService
from app.services.email.payment_link import PaymentLinkEmailPayload, send_payment_link_email
from app.services.email.payment_reminder import PaymentReminderEmailPayload, send_payment_reminder_email
from app.services.notifications.service import NotificationService
from app.services.payments.authorize_provider import AuthorizePaymentProvider
from app.services.payments.base import PaymentProviderError
from app.services.payments.paypal_provider import PayPalPaymentProvider
from app.services.role_access import is_sales_area_leader, is_sales_staff

logger = logging.getLogger(__name__)

PAYMENT_ROLES = frozenset({"ADMIN", "BRANCH_MANAGER", "SALES_REP", "SUB_SELLER", "AREA_LEADER"})

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
        if user.role.code in ("ADMIN", "BRANCH_MANAGER", "SALES_REP", "SUB_SELLER"):
            return
        if is_sales_area_leader(user):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    @property
    def stub_mode(self) -> bool:
        """Sin cobro real: PAYMENT_TEST o proveedores no configurados."""
        if self.settings.payment_test:
            return True
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
            payment_test=self.settings.payment_test,
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
            amount_paid=link.amount_paid or Decimal("0.00"),
            remaining_amount=remaining_amount(link),
            allow_partial=bool(link.allow_partial),
            currency=link.currency,
            provider=link.provider,  # type: ignore[arg-type]
            status=link.status,  # type: ignore[arg-type]
            description=link.description,
            payment_url=link.payment_url,
            external_checkout_url=link.external_checkout_url,
            paid_at=link.paid_at,
            remainder_due_on=getattr(link, "remainder_due_on", None),
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
        page: int = 1,
        page_size: int = 10,
        link_status: str | None = None,
        unlinked: bool = False,
        customer_email: str | None = None,
    ) -> tuple[list[PaymentLinkResponse], int]:
        self.ensure_access(user)
        filters = [PaymentLink.merchant_id == merchant_id]
        if is_sales_staff(user) or (is_sales_area_leader(user) and created_by_user_id is None):
            filters.append(PaymentLink.created_by_user_id == user.id)
        elif created_by_user_id is not None:
            filters.append(PaymentLink.created_by_user_id == created_by_user_id)
        if link_status is not None:
            allowed = {item.value for item in PaymentLinkStatus}
            if link_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Estado de pago inválido",
                )
            filters.append(PaymentLink.status == link_status)
        if unlinked:
            filters.append(PaymentLink.prospect_id.is_(None))
        if customer_email:
            filters.append(PaymentLink.customer_email == customer_email.strip().lower())

        total = self.db.execute(
            select(func.count()).select_from(PaymentLink).where(*filters)
        ).scalar_one()

        stmt = (
            select(PaymentLink)
            .options(joinedload(PaymentLink.created_by))
            .where(*filters)
            .order_by(PaymentLink.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = self.db.execute(stmt).unique().scalars().all()
        return [self._to_response(row) for row in rows], int(total)

    @staticmethod
    def normalize_create_amount(*, allow_partial: bool, amount: Decimal) -> Decimal:
        """Pago inicial: 3000 USD fijos, salvo que se marque parcial (monto menor)."""
        if not allow_partial:
            return STANDARD_INITIAL_PAYMENT
        if amount <= 0 or amount >= STANDARD_INITIAL_PAYMENT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Con pago parcial el monto debe ser mayor a 0 y menor a 3000 USD",
            )
        return amount

    def create_link(
        self,
        user: User,
        payload: PaymentLinkCreate,
        *,
        merchant_id: int,
        standardize_amount: bool = True,
    ) -> PaymentLinkCreateResult:
        self.ensure_access(user)
        if not self.settings.payments_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Los pagos están deshabilitados")
        if payload.provider not in ACTIVE_PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Proveedor no disponible. Usa Authorize.net o PayPal.",
            )

        amount = (
            self.normalize_create_amount(allow_partial=bool(payload.allow_partial), amount=payload.amount)
            if standardize_amount
            else payload.amount
        )
        if standardize_amount and not payload.allow_partial and payload.prospect_id is not None:
            from app.services.prospects import ProspectService

            prospect_svc = ProspectService(self.db)
            prospect = prospect_svc._get_prospect_for_user(
                user, payload.prospect_id, merchant_id=merchant_id
            )
            leftover = remaining_to_standard(prospect_svc.list_linked_payment_links(prospect))
            if leftover <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Este prospecto ya cubrió el pago inicial de 3000 USD",
                )
            amount = leftover
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El monto debe ser mayor a 0",
            )

        token = uuid.uuid4().hex
        portal_url = f"{self.settings.portal_base_url}/pagar/{token}"
        success_url = f"{portal_url}?paid=1"
        cancel_url = portal_url

        external_id: str | None = None
        external_url: str | None = None

        try:
            # El monto lo define el vendedor. En PAYMENT_TEST el portal aprueba con "Pagar".
            if not self.settings.payment_test:
                external_id, external_url = self._create_provider_checkout(
                    provider=payload.provider,
                    amount=amount,
                    currency=payload.currency,
                    customer_email=str(payload.customer_email),
                    customer_first_name=payload.customer_first_name,
                    customer_last_name=payload.customer_last_name,
                    customer_phone=payload.customer_phone,
                    description=payload.description,
                    reference_id=token,
                    return_url=success_url,
                    cancel_url=cancel_url,
                )
        except PaymentProviderError as exc:
            logger.warning("Checkout externo falló (%s); usando portal local", exc)
            if not self.stub_mode:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(exc),
                ) from exc

        use_portal_url = (
            self.settings.payment_test
            or payload.provider == PaymentProvider.AUTHORIZE.value
            or not external_url
        )
        link = PaymentLink(
            public_token=token,
            created_by_user_id=user.id,
            merchant_id=merchant_id,
            prospect_id=payload.prospect_id,
            customer_first_name=payload.customer_first_name.strip(),
            customer_last_name=payload.customer_last_name.strip(),
            customer_email=str(payload.customer_email).strip().lower(),
            customer_phone=payload.customer_phone.strip(),
            amount=amount,
            amount_paid=Decimal("0.00"),
            allow_partial=bool(payload.allow_partial),
            remainder_due_on=payload.remainder_due_on,
            currency=payload.currency.upper(),
            provider=payload.provider,
            status=PaymentLinkStatus.PENDING.value,
            description=payload.description,
            # Authorize Accept Hosted / modo test: el link compartible es el portal.
            payment_url=portal_url if use_portal_url else external_url,
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
            email_sent = self._send_link_email(link, merchant_id=merchant_id)
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
        if link.status != PaymentLinkStatus.PENDING.value or remaining_amount(link) < link.amount:
            raise HTTPException(status_code=400, detail="Solo se pueden cancelar links pendientes sin cobros")
        link.status = PaymentLinkStatus.CANCELLED.value
        if link.prospect_id is not None:
            from app.services.prospects import ProspectService

            ProspectService(self.db).on_payment_cancelled(actor=user, link=link)
        self.db.commit()
        self.db.refresh(link)
        return self._to_response(link)

    def update_remainder_due_on(
        self,
        user: User,
        link_id: int,
        remainder_due_on: date,
        *,
        merchant_id: int,
    ) -> PaymentLinkResponse:
        """Actualiza la fecha acordada para completar el saldo (pago parcial)."""
        self.ensure_access(user)
        link = self._get_link_for_user(user, link_id, merchant_id=merchant_id)
        closed = {
            PaymentLinkStatus.CANCELLED.value,
            PaymentLinkStatus.EXPIRED.value,
        }
        if link.status in closed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede cambiar la fecha de un cobro cancelado o vencido",
            )

        targets = [link]
        if link.prospect_id is not None:
            from app.services.prospects import ProspectService

            prospect_svc = ProspectService(self.db)
            prospect = prospect_svc._get_prospect_for_user(
                user, link.prospect_id, merchant_id=merchant_id
            )
            prospect_links = prospect_svc.list_linked_payment_links(prospect)
            if remaining_to_standard(prospect_links) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Este prospecto ya cubrió el pago inicial de 3000 USD",
                )
            targets = [item for item in prospect_links if item.status not in closed] or [link]
        elif remaining_amount(link) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este cobro ya está saldado",
            )

        for item in targets:
            item.remainder_due_on = remainder_due_on
        self.db.commit()
        self.db.refresh(link)
        return self._to_response(link)

    def _send_link_email(self, link: PaymentLink, *, merchant_id: int | None) -> bool:
        leftover = remaining_amount(link)
        payment_url = link.payment_url
        if not payment_url:
            return False
        merchant_name: str | None = None
        if merchant_id:
            merchant_row = self.db.get(Merchant, merchant_id)
            merchant_name = merchant_row.name if merchant_row else None
        paid = Decimal(link.amount_paid or 0)
        if paid > 0:
            return send_payment_reminder_email(
                PaymentReminderEmailPayload(
                    recipient_email=link.customer_email,
                    first_name=link.customer_first_name,
                    remaining=leftover,
                    total=link.amount,
                    paid=paid,
                    currency=link.currency,
                    payment_url=payment_url,
                    payment_link_id=link.id,
                    description=link.description,
                    provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
                )
            )
        return send_payment_link_email(
            PaymentLinkEmailPayload(
                recipient_email=link.customer_email,
                first_name=link.customer_first_name,
                amount=leftover or link.amount,
                currency=link.currency,
                payment_url=payment_url,
                provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
                payment_link_id=link.id,
                description=link.description,
                merchant_name=merchant_name,
            )
        )

    def resend_link_email(
        self, user: User, link_id: int, *, merchant_id: int
    ) -> PaymentLinkCreateResult:
        self.ensure_access(user)
        link = self._get_link_for_user(user, link_id, merchant_id=merchant_id)
        if not is_open_payment(link):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se puede reenviar un link pendiente o con saldo",
            )
        email_sent = self._send_link_email(link, merchant_id=merchant_id)
        if not email_sent:
            logger.warning(
                "No se pudo reenviar email de pago a %s (link_id=%s)",
                link.customer_email,
                link.id,
            )
        return PaymentLinkCreateResult(link=self._to_response(link), email_sent=email_sent)

    def send_balance_for_prospect(
        self, user: User, prospect_id: int, *, merchant_id: int
    ) -> PaymentLinkCreateResult:
        """Reenvía el link abierto o crea uno por el saldo hasta 3000 USD."""
        from app.services.prospects import ProspectService

        self.ensure_access(user)
        prospect_svc = ProspectService(self.db)
        prospect = prospect_svc._get_prospect_for_user(user, prospect_id, merchant_id=merchant_id)
        links = prospect_svc.list_linked_payment_links(prospect)
        leftover = remaining_to_standard(links)
        if leftover <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este prospecto ya cubrió el pago inicial de 3000 USD",
            )
        open_link = next((link for link in links if is_open_payment(link)), None)
        if open_link is not None:
            email_sent = self._send_link_email(open_link, merchant_id=merchant_id)
            if not email_sent:
                logger.warning(
                    "No se pudo enviar email de saldo a %s (link_id=%s)",
                    open_link.customer_email,
                    open_link.id,
                )
            return PaymentLinkCreateResult(link=self._to_response(open_link), email_sent=email_sent)

        last = links[0] if links else None
        provider = last.provider if last else self.settings.payments_default_provider_normalized
        if provider not in ACTIVE_PROVIDERS:
            provider = PaymentProvider.AUTHORIZE.value
        remainder_due_on = next(
            (link.remainder_due_on for link in links if getattr(link, "remainder_due_on", None) is not None),
            None,
        )
        payload = PaymentLinkCreate(
            customer_first_name=prospect.first_name,
            customer_last_name=prospect.last_name,
            customer_email=prospect.email,
            customer_phone=prospect.phone,
            amount=leftover,
            provider=provider,  # type: ignore[arg-type]
            prospect_id=prospect.id,
            send_email=True,
            allow_partial=False,
            remainder_due_on=remainder_due_on,
            description="Saldo para completar el pago inicial de USD 3000",
        )
        return self.create_link(user, payload, merchant_id=merchant_id, standardize_amount=False)

    def get_public_link(self, token: str) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        leftover = remaining_amount(link)
        can_pay = is_open_payment(link) and self.settings.payments_enabled
        checkout_url = link.external_checkout_url if not self.stub_mode else None
        hosted_payment_token: str | None = None
        if (
            not self.stub_mode
            and not link.allow_partial
            and link.provider == PaymentProvider.AUTHORIZE.value
            and link.external_checkout_id
        ):
            hosted_payment_token = link.external_checkout_id
            checkout_url = self.authorize.hosted_base
        return PublicPaymentLinkResponse(
            customer_first_name=link.customer_first_name,
            customer_last_name=link.customer_last_name,
            customer_email=link.customer_email,
            amount=link.amount,
            amount_paid=link.amount_paid or Decimal("0.00"),
            remaining_amount=leftover,
            allow_partial=bool(link.allow_partial),
            currency=link.currency,
            provider=link.provider,  # type: ignore[arg-type]
            status=link.status,  # type: ignore[arg-type]
            description=link.description,
            stub_mode=self.stub_mode,
            payment_test=self.settings.payment_test,
            can_pay=can_pay,
            checkout_url=checkout_url,
            hosted_payment_token=hosted_payment_token,
            provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
        )

    def prepare_public_checkout(
        self,
        token: str,
        *,
        amount: Decimal | None = None,
    ) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        charge = self._resolve_charge_amount(link, amount)
        if self.stub_mode or self.settings.payment_test:
            link.pending_charge_amount = charge
            self.db.commit()
            return self.get_public_link(token)

        portal_url = f"{self.settings.portal_base_url}/pagar/{link.public_token}"
        try:
            external_id, external_url = self._create_provider_checkout(
                provider=link.provider,
                amount=charge,
                currency=link.currency,
                customer_email=link.customer_email,
                customer_first_name=link.customer_first_name,
                customer_last_name=link.customer_last_name,
                customer_phone=link.customer_phone,
                description=link.description,
                reference_id=link.public_token,
                return_url=f"{portal_url}?paid=1",
                cancel_url=portal_url,
            )
        except PaymentProviderError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        if not external_url and not external_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay un checkout disponible para este proveedor",
            )
        link.pending_charge_amount = charge
        link.external_checkout_id = external_id
        link.external_checkout_url = external_url
        self.db.commit()
        leftover = remaining_amount(link)
        hosted_payment_token = None
        checkout_url = external_url
        if link.provider == PaymentProvider.AUTHORIZE.value and external_id:
            hosted_payment_token = external_id
            checkout_url = self.authorize.hosted_base
        return PublicPaymentLinkResponse(
            customer_first_name=link.customer_first_name,
            customer_last_name=link.customer_last_name,
            customer_email=link.customer_email,
            amount=link.amount,
            amount_paid=link.amount_paid or Decimal("0.00"),
            remaining_amount=leftover,
            allow_partial=bool(link.allow_partial),
            currency=link.currency,
            provider=link.provider,  # type: ignore[arg-type]
            status=link.status,  # type: ignore[arg-type]
            description=link.description,
            stub_mode=self.stub_mode,
            payment_test=self.settings.payment_test,
            can_pay=True,
            checkout_url=checkout_url,
            hosted_payment_token=hosted_payment_token,
            provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
        )

    def complete_public_payment(
        self,
        token: str,
        *,
        amount: Decimal | None = None,
    ) -> PublicPaymentLinkResponse:
        link = self._get_link_by_token(token)
        if not is_open_payment(link):
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
        self._apply_received_payment(link, charged=self._resolve_charge_amount(link, amount))
        self.db.commit()
        return self.get_public_link(token)

    def confirm_paypal_return(self, token: str, *, order_id: str | None = None) -> PublicPaymentLinkResponse:
        """Confirma el retorno del checkout (PayPal capture o Authorize post-pago)."""
        link = self._get_link_by_token(token)
        if link.provider == PaymentProvider.PAYPAL.value:
            if order_id and link.external_checkout_id and order_id != link.external_checkout_id:
                raise HTTPException(status_code=400, detail="La orden PayPal no coincide con el link")
            self._capture_paypal_if_completed(link)
            self.db.commit()
            return self.get_public_link(token)
        if link.provider == PaymentProvider.AUTHORIZE.value:
            # Authorize redirige a ?paid=1 solo después de pagar (botón Continuar).
            # El webhook puede haber marcado paid; si sigue pending, lo confirmamos acá.
            if is_open_payment(link):
                self._apply_received_payment(link)
                self.db.commit()
            return self.get_public_link(token)
        raise HTTPException(status_code=400, detail="Este link no admite confirmación de retorno")

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
                if link and is_open_payment(link):
                    self._apply_received_payment(link)
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
                link = self._get_link_by_invoice_ref(str(invoice))
                if link and is_open_payment(link):
                    self._apply_received_payment(link)
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
        if not is_payment_satisfied(link):
            raise HTTPException(status_code=400, detail="El pago debe estar completado antes de registrar al cliente")
        if link.client_id is not None:
            raise HTTPException(status_code=400, detail="Este pago ya tiene un cliente registrado")

        try:
            from app.services.sources import require_active_source_code

            source = require_active_source_code(self.db, payload.source, required=True)
        except ValueError:
            source = ClientSource.OTHER.value

        if link.prospect_id is not None:
            from app.models.prospect import Prospect
            from app.services.prospects import CONVERSION_REQUIREMENTS_DETAIL, ProspectService

            prospect = self.db.get(Prospect, link.prospect_id)
            if prospect is not None:
                if prospect.converted_client_id is not None:
                    raise HTTPException(
                        status_code=400,
                        detail="Este pago ya está vinculado a un cliente vía el prospecto",
                    )
                psvc = ProspectService(self.db)
                if not psvc._ready_for_conversion(prospect):
                    raise HTTPException(
                        status_code=400,
                        detail=CONVERSION_REQUIREMENTS_DETAIL,
                    )
                client = psvc.convert_to_client(
                    prospect=prospect, actor=user, from_payment=True
                )
                return client.id, "Cliente registrado correctamente"

        resolved_merchant_id = payload.merchant_id or link.merchant_id or merchant_id
        client_service = ClientService(self.db)
        client, portal_pw = client_service.create_client(
            actor=user,
            first_name=link.customer_first_name,
            last_name=link.customer_last_name,
            email=link.customer_email,
            phone=link.customer_phone,
            source=source,
            merchant_id=resolved_merchant_id,
            commit=False,
        )
        link.client_id = client.id
        link.client_registered_at = datetime.now(timezone.utc)
        self.db.commit()
        if portal_pw is not None:
            client_service._send_client_portal_welcome(client, portal_pw)
        return client.id, "Cliente registrado correctamente"

    def _capture_paypal_if_completed(self, link: PaymentLink) -> None:
        if not link.external_checkout_id or not self.paypal.is_configured:
            return
        if not is_open_payment(link):
            return
        try:
            order = self.paypal.get_order(link.external_checkout_id)
            order_status = str(order.get("status", "")).upper()
            if order_status == "COMPLETED":
                self._apply_received_payment(link)
                return
            if order_status == "APPROVED":
                capture = self.paypal.capture_order(link.external_checkout_id)
                if str(capture.get("status", "")).upper() == "COMPLETED":
                    self._apply_received_payment(link)
        except PaymentProviderError as exc:
            logger.warning("No se pudo capturar orden PayPal %s: %s", link.external_checkout_id, exc)

    def _resolve_charge_amount(self, link: PaymentLink, amount: Decimal | None) -> Decimal:
        leftover = remaining_amount(link)
        if leftover <= 0:
            raise HTTPException(status_code=400, detail="Este link ya no tiene saldo pendiente")
        if not is_open_payment(link):
            raise HTTPException(status_code=400, detail="Este link ya no está disponible para pago")
        # El link cobra el monto enviado por el vendedor (saldo de este link).
        charge = leftover
        if charge <= 0 or charge > leftover:
            raise HTTPException(
                status_code=400,
                detail=f"El monto debe ser mayor a 0 y hasta {link.currency} {leftover:.2f}",
            )
        return charge.quantize(Decimal("0.01"))

    def _create_provider_checkout(
        self,
        *,
        provider: str,
        amount: Decimal,
        currency: str,
        customer_email: str,
        customer_first_name: str,
        customer_last_name: str,
        customer_phone: str,
        description: str | None,
        reference_id: str,
        return_url: str,
        cancel_url: str,
    ) -> tuple[str | None, str | None]:
        if provider == PaymentProvider.AUTHORIZE.value and self.authorize.is_configured:
            result = self.authorize.create_checkout_link(
                amount=amount,
                currency=currency,
                customer_email=customer_email,
                customer_first_name=customer_first_name,
                customer_last_name=customer_last_name,
                customer_phone=customer_phone,
                description=description,
                reference_id=reference_id,
                return_url=return_url,
                cancel_url=cancel_url,
            )
            return result.external_id, result.checkout_url
        if provider == PaymentProvider.PAYPAL.value and self.paypal.is_configured:
            result = self.paypal.create_checkout_link(
                amount=amount,
                currency=currency,
                customer_email=customer_email,
                customer_first_name=customer_first_name,
                customer_last_name=customer_last_name,
                customer_phone=customer_phone,
                description=description,
                reference_id=reference_id,
                return_url=return_url,
                cancel_url=cancel_url,
            )
            return result.external_id, result.checkout_url
        return None, None

    def _apply_received_payment(self, link: PaymentLink, *, charged: Decimal | None = None) -> None:
        if link.status == PaymentLinkStatus.PAID.value:
            return
        charge = charged or link.pending_charge_amount or remaining_amount(link)
        leftover = remaining_amount(link)
        if charge <= 0:
            return
        if charge > leftover:
            charge = leftover
        link.amount_paid = Decimal(link.amount_paid or 0) + charge
        link.pending_charge_amount = None
        if remaining_amount(link) <= 0:
            link.status = PaymentLinkStatus.PAID.value
            link.paid_at = datetime.now(timezone.utc)
        else:
            link.status = PaymentLinkStatus.PARTIAL.value
            if link.paid_at is None:
                link.paid_at = datetime.now(timezone.utc)
            link.external_checkout_id = None
            link.external_checkout_url = None

        converted_client = None
        if link.prospect_id is None:
            from app.models.prospect import Prospect

            linked = self.db.execute(
                select(Prospect).where(Prospect.payment_link_id == link.id)
            ).scalar_one_or_none()
            if linked is not None:
                link.prospect_id = linked.id
        if link.prospect_id is not None:
            from app.services.prospects import ProspectService

            converted_client = ProspectService(self.db).on_payment_completed(link)

        # Si ya se convirtió, convert_to_client ya envió la notif combinada.
        if converted_client is not None:
            return

        recipients: list[User] = []
        seen: set[int] = set()

        def _add(user: User | None) -> None:
            if user is None or not user.is_active or user.id is None:
                return
            if user.id in seen:
                return
            seen.add(user.id)
            recipients.append(user)

        creator = self.db.get(User, link.created_by_user_id)
        _add(creator)
        if link.prospect_id is not None:
            from app.models.prospect import Prospect

            prospect = self.db.get(Prospect, link.prospect_id)
            if prospect is not None:
                _add(prospect.assigned_to)

        if not recipients:
            return

        leftover_now = remaining_amount(link)
        customer = f"{link.customer_first_name} {link.customer_last_name}"
        if leftover_now > 0:
            title = "Pago parcial recibido"
            body = (
                f"{customer} pagó {link.currency} {charge:.2f} de {link.amount:.2f}. "
                f"Saldo pendiente: {link.currency} {leftover_now:.2f}."
            )
        else:
            title = "Pago recibido"
            body = f"{customer} completó el pago de {link.currency} {link.amount:.2f}."

        NotificationService(self.db).notify(
            event_type="PAYMENT_LINK_COMPLETED",
            users=recipients,
            title=title,
            body=body,
            payload={
                "payment_link_id": link.id,
                "prospect_id": link.prospect_id,
                "customer_email": link.customer_email,
                "customer_name": customer,
                "amount": str(charge),
                "total_amount": str(link.amount),
                "amount_paid": str(link.amount_paid or 0),
                "remaining_amount": str(leftover_now),
                "currency": link.currency,
            },
            commit=True,
        )

    def _get_link_by_token(self, token: str, *, raise_if_missing: bool = True) -> PaymentLink | None:
        link = self.db.execute(
            select(PaymentLink).where(PaymentLink.public_token == token)
        ).scalar_one_or_none()
        if link is None and raise_if_missing:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        return link

    def _get_link_by_invoice_ref(self, invoice: str) -> PaymentLink | None:
        """Authorize invoiceNumber max 20 chars; el token del CRM es más largo."""
        invoice = invoice.strip()
        if not invoice:
            return None
        link = self._get_link_by_token(invoice, raise_if_missing=False)
        if link is not None:
            return link
        return self.db.execute(
            select(PaymentLink)
            .where(PaymentLink.public_token.startswith(invoice))
            .order_by(PaymentLink.id.desc())
        ).scalars().first()

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
        if is_sales_staff(user) and link.created_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        return link
