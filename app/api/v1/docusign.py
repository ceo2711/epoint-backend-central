from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.schemas.docusign import (
    DocusignConnectionResponse,
    DocusignConsentUrlResponse,
    DocusignWebhookUrlResponse,
    DocusignEnvelopeResponse,
    DocusignRegisterClientRequest,
    DocusignRegisterClientResponse,
    DocusignSendEnvelopeRequest,
    DocusignSendEnvelopeResponse,
    DocusignTemplateDetailResponse,
    DocusignTemplateResponse,
)
from app.services.docusign.service import DocusignService

router = APIRouter(prefix="/docusign", tags=["DocuSign"])


@router.get("/connection", response_model=DocusignConnectionResponse)
def get_connection(current_user: CurrentUser, db: DbSession) -> DocusignConnectionResponse:
    """Estado de la integración (credenciales en variables de entorno del servidor)."""
    return DocusignService(db).get_connection(current_user)


@router.get("/consent-url", response_model=DocusignConsentUrlResponse)
def get_consent_url(current_user: CurrentUser, db: DbSession) -> DocusignConsentUrlResponse:
    """Enlace de consentimiento JWT (obligatorio una vez por cuenta demo/prod)."""
    return DocusignService(db).get_consent_url(current_user)


@router.get("/webhook-url", response_model=DocusignWebhookUrlResponse)
def get_webhook_url(current_user: CurrentUser, db: DbSession) -> DocusignWebhookUrlResponse:
    """URL pública para DocuSign Connect (requiere BACKEND_PUBLIC_URL)."""
    return DocusignService(db).get_webhook_url(current_user)


@router.get("/templates", response_model=list[DocusignTemplateResponse])
def list_templates(current_user: CurrentUser, db: DbSession) -> list[DocusignTemplateResponse]:
    return DocusignService(db).list_templates(current_user)


@router.get("/templates/{template_id}", response_model=DocusignTemplateDetailResponse)
def get_template_detail(
    template_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> DocusignTemplateDetailResponse:
    return DocusignService(db).get_template_detail(current_user, template_id)


@router.get("/envelopes", response_model=list[DocusignEnvelopeResponse])
def list_envelopes(
    current_user: CurrentUser,
    db: DbSession,
    sent_by_user_id: int | None = Query(None, ge=1),
) -> list[DocusignEnvelopeResponse]:
    return DocusignService(db).list_envelopes(current_user, sent_by_user_id=sent_by_user_id)


@router.get("/clients/{client_id}/envelopes", response_model=list[DocusignEnvelopeResponse])
def list_client_envelopes(
    client_id: int,
    current_user: CurrentUser,
    db: DbSession,
) -> list[DocusignEnvelopeResponse]:
    return DocusignService(db).list_client_envelopes(current_user, client_id)


@router.post("/envelopes/sync-pending", response_model=list[DocusignEnvelopeResponse])
def sync_pending_envelopes(
    current_user: CurrentUser,
    db: DbSession,
    sent_by_user_id: int | None = Query(None, ge=1),
) -> list[DocusignEnvelopeResponse]:
    """Actualiza estados pendientes consultando DocuSign."""
    return DocusignService(db).sync_pending_envelopes(
        current_user,
        sent_by_user_id=sent_by_user_id,
    )


@router.post("/envelopes", response_model=DocusignSendEnvelopeResponse)
def send_envelope(
    payload: DocusignSendEnvelopeRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> DocusignSendEnvelopeResponse:
    return DocusignService(db).send_envelope(current_user, payload)


@router.post("/envelopes/{envelope_id}/sync", response_model=DocusignEnvelopeResponse)
def sync_envelope_status(
    envelope_id: int,
    current_user: CurrentUser,
    db: DbSession,
) -> DocusignEnvelopeResponse:
    return DocusignService(db).sync_envelope_status(current_user, envelope_id)


@router.post("/envelopes/{envelope_id}/register-client", response_model=DocusignRegisterClientResponse)
def register_client_from_envelope(
    envelope_id: int,
    payload: DocusignRegisterClientRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> DocusignRegisterClientResponse:
    """Registra al firmante como cliente CRM y lo envía a revisión de onboarding."""
    service = DocusignService(db)
    row, client = service.register_client_from_envelope(
        current_user,
        envelope_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        phone=payload.phone,
        source=payload.source.value,
        merchant_id=payload.merchant_id,
    )
    return DocusignRegisterClientResponse(
        envelope=service._map_envelope(row),
        client_id=client.id,
    )


@router.get("/envelopes/{envelope_id}/document/sent")
def download_sent_document(
    envelope_id: int,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    content, filename = DocusignService(db).get_sent_document(current_user, envelope_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/envelopes/{envelope_id}/document")
def download_signed_document(
    envelope_id: int,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    content, filename = DocusignService(db).get_signed_document(current_user, envelope_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/webhook")
async def docusign_connect_webhook(request: Request, db: DbSession) -> dict:
    """DocuSign Connect — eventos de firma (público, validado por HMAC)."""
    body = await request.body()
    signature = request.headers.get("X-DocuSign-Signature-1")
    content_type = request.headers.get("content-type")
    return DocusignService(db).handle_connect_webhook(
        body,
        signature=signature,
        content_type=content_type,
    )
