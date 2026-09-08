from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from typing import Annotated

from app.api.deps import ActiveMerchantId, CurrentUser, DbSession
from app.schemas.docusign import (
    DocusignConnectionResponse,
    DocusignConsentUrlResponse,
    DocusignWebhookUrlResponse,
    DocusignEnvelopeResponse,
    DocusignRegisterClientRequest,
    DocusignRegisterClientResponse,
    DocusignResendReminderResponse,
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
    merchant_id: ActiveMerchantId,
    db: DbSession,
    sent_by_user_id: int | None = Query(None, ge=1),
) -> list[DocusignEnvelopeResponse]:
    return DocusignService(db).list_envelopes(
        current_user,
        merchant_id=merchant_id,
        sent_by_user_id=sent_by_user_id,
    )


@router.get("/clients/{client_id}/envelopes", response_model=list[DocusignEnvelopeResponse])
def list_client_envelopes(
    client_id: int,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> list[DocusignEnvelopeResponse]:
    return DocusignService(db).list_client_envelopes(
        current_user,
        client_id,
        merchant_id=merchant_id,
    )


@router.post("/envelopes/sync-pending", response_model=list[DocusignEnvelopeResponse])
def sync_pending_envelopes(
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
    sent_by_user_id: int | None = Query(None, ge=1),
) -> list[DocusignEnvelopeResponse]:
    """Actualiza estados pendientes consultando DocuSign."""
    return DocusignService(db).sync_pending_envelopes(
        current_user,
        merchant_id=merchant_id,
        sent_by_user_id=sent_by_user_id,
    )


@router.post("/envelopes", response_model=DocusignSendEnvelopeResponse)
def send_envelope(
    payload: DocusignSendEnvelopeRequest,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> DocusignSendEnvelopeResponse:
    return DocusignService(db).send_envelope(current_user, payload, merchant_id=merchant_id)


@router.post("/envelopes/manual", response_model=DocusignEnvelopeResponse)
async def upload_manual_contract(
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    prospect_id: Annotated[int | None, Form()] = None,
    client_id: Annotated[int | None, Form()] = None,
    subject: Annotated[str | None, Form()] = None,
) -> DocusignEnvelopeResponse:
    """Carga un contrato físico firmado (PDF o foto) y lo marca como firmado."""
    file_bytes = await file.read()
    return DocusignService(db).upload_manual_contract(
        current_user,
        file_bytes=file_bytes,
        filename=file.filename or "contrato.pdf",
        content_type=file.content_type or "",
        merchant_id=merchant_id,
        prospect_id=prospect_id,
        client_id=client_id,
        subject=subject,
    )


@router.post("/envelopes/{envelope_id}/resend-reminder", response_model=DocusignResendReminderResponse)
def resend_envelope_signing_reminder(
    envelope_id: int,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> DocusignResendReminderResponse:
    envelope, email_sent, docusign_resent = DocusignService(db).resend_signing_reminder(
        current_user,
        envelope_id,
        merchant_id=merchant_id,
    )
    if email_sent:
        message = "Enviamos un recordatorio para que el cliente firme el contrato."
    else:
        message = (
            "No se pudo enviar el email de recordatorio. "
            "Pedile al cliente que revise el correo de DocuSign."
        )
    return DocusignResendReminderResponse(
        envelope=envelope,
        message=message,
        email_sent=email_sent,
        docusign_resent=docusign_resent,
    )


@router.post("/envelopes/{envelope_id}/sync", response_model=DocusignEnvelopeResponse)
def sync_envelope_status(
    envelope_id: int,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> DocusignEnvelopeResponse:
    return DocusignService(db).sync_envelope_status(
        current_user,
        envelope_id,
        merchant_id=merchant_id,
    )


@router.post("/envelopes/{envelope_id}/register-client", response_model=DocusignRegisterClientResponse)
def register_client_from_envelope(
    envelope_id: int,
    payload: DocusignRegisterClientRequest,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> DocusignRegisterClientResponse:
    """Registra al firmante como cliente CRM y lo envía a revisión de onboarding."""
    from app.services.sources import require_active_source_code

    try:
        source = require_active_source_code(db, payload.source, required=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    service = DocusignService(db)
    row, client = service.register_client_from_envelope(
        current_user,
        envelope_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        phone=payload.phone,
        source=source,
        merchant_id=payload.merchant_id,
        active_merchant_id=merchant_id,
    )
    return DocusignRegisterClientResponse(
        envelope=service._map_envelope(row),
        client_id=client.id,
    )


@router.get("/envelopes/{envelope_id}/document/sent")
def download_sent_document(
    envelope_id: int,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> StreamingResponse:
    content, filename = DocusignService(db).get_sent_document(
        current_user,
        envelope_id,
        merchant_id=merchant_id,
    )
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/envelopes/{envelope_id}/document")
def download_signed_document(
    envelope_id: int,
    current_user: CurrentUser,
    merchant_id: ActiveMerchantId,
    db: DbSession,
) -> StreamingResponse:
    content, filename = DocusignService(db).get_signed_document(
        current_user,
        envelope_id,
        merchant_id=merchant_id,
    )
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
