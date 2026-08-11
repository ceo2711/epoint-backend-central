from typing import Annotated, Any
import math

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import ActiveMerchantId, CurrentUser, DbSession, require_permissions
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.payment import (
    PaymentConfigResponse,
    PaymentLinkCreate,
    PaymentLinkCreateResponse,
    PaymentLinkResponse,
    PaymentRegisterClientRequest,
    PaymentRegisterClientResponse,
    PublicPaymentLinkResponse,
)
from app.services.payments.service import PaymentService

router = APIRouter(prefix="/payments", tags=["Pagos"])


@router.get("/config", response_model=PaymentConfigResponse)
def get_payment_config(current_user: CurrentUser, db: DbSession) -> PaymentConfigResponse:
    """Estado de proveedores (solo lectura; la configuración vive en variables de entorno)."""
    return PaymentService(db).get_config(current_user)


@router.get("/links", response_model=PaginatedResponse[PaymentLinkResponse])
def list_payment_links(
    current_user: Annotated[User, Depends(require_permissions("payments:read"))],
    merchant_id: ActiveMerchantId,
    db: DbSession,
    created_by_user_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> PaginatedResponse[PaymentLinkResponse]:
    items, total = PaymentService(db).list_links(
        current_user,
        merchant_id=merchant_id,
        created_by_user_id=created_by_user_id,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.post("/links", response_model=PaymentLinkCreateResponse)
def create_payment_link(
    payload: PaymentLinkCreate,
    current_user: Annotated[User, Depends(require_permissions("payments:create"))],
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> PaymentLinkCreateResponse:
    result = PaymentService(db).create_link(current_user, payload, merchant_id=merchant_id)
    if result.email_sent:
        message = "Link de pago generado y enviado por email al cliente."
    elif payload.send_email:
        message = (
            "Link de pago generado. No se pudo enviar el email — "
            "compartilo manualmente con el cliente."
        )
    else:
        message = "Link de pago generado. Compartilo con el cliente para que complete el pago."
    return PaymentLinkCreateResponse(
        link=result.link,
        message=message,
        email_sent=result.email_sent,
    )


@router.post("/links/{link_id}/cancel", response_model=PaymentLinkResponse)
def cancel_payment_link(
    link_id: int,
    current_user: Annotated[User, Depends(require_permissions("payments:create"))],
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> PaymentLinkResponse:
    return PaymentService(db).cancel_link(current_user, link_id, merchant_id=merchant_id)


@router.post("/links/{link_id}/register-client", response_model=PaymentRegisterClientResponse)
def register_client_from_payment(
    link_id: int,
    payload: PaymentRegisterClientRequest,
    current_user: Annotated[User, Depends(require_permissions("payments:create", "clients:create"))],
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> PaymentRegisterClientResponse:
    client_id, message = PaymentService(db).register_client_from_link(
        current_user,
        link_id,
        payload,
        merchant_id=merchant_id,
    )
    return PaymentRegisterClientResponse(client_id=client_id, message=message)


@router.get("/public/{token}", response_model=PublicPaymentLinkResponse)
def get_public_payment_link(token: str, db: DbSession) -> PublicPaymentLinkResponse:
    """Página pública de pago — sin autenticación."""
    return PaymentService(db).get_public_link(token)


@router.post("/public/{token}/complete", response_model=PublicPaymentLinkResponse)
def complete_public_payment_stub(token: str, db: DbSession) -> PublicPaymentLinkResponse:
    """Completa el pago en modo stub o confirma retorno PayPal."""
    return PaymentService(db).complete_public_payment(token)


@router.post("/public/{token}/confirm-return", response_model=PublicPaymentLinkResponse)
def confirm_payment_return(
    token: str,
    db: DbSession,
    order_id: str | None = Query(None),
) -> PublicPaymentLinkResponse:
    """Confirma el pago al volver del checkout (PayPal o Authorize.net)."""
    return PaymentService(db).confirm_paypal_return(token, order_id=order_id)


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, db: DbSession) -> dict[str, Any]:
    payload = await request.json()
    return PaymentService(db).handle_paypal_webhook(payload)


@router.post("/webhooks/authorize")
async def authorize_webhook(request: Request, db: DbSession) -> dict[str, Any]:
    payload = await request.json()
    return PaymentService(db).handle_authorize_webhook(payload)
