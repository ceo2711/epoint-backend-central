from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import MessageResponse
from app.schemas.docusign import (
    DocusignConnectRequest,
    DocusignConnectionResponse,
    DocusignConsentUrlResponse,
    DocusignEnvelopeResponse,
    DocusignSendEnvelopeRequest,
    DocusignSendEnvelopeResponse,
    DocusignTemplateDetailResponse,
    DocusignTemplateResponse,
)
from app.services.docusign.service import DocusignService

router = APIRouter(prefix="/docusign", tags=["DocuSign"])


@router.get("/connection", response_model=DocusignConnectionResponse)
def get_connection(current_user: CurrentUser, db: DbSession) -> DocusignConnectionResponse:
    return DocusignService(db).get_connection(current_user)


@router.post("/connection", response_model=DocusignConnectionResponse)
def connect_docusign(
    payload: DocusignConnectRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> DocusignConnectionResponse:
    return DocusignService(db).connect(current_user, payload)


@router.delete("/connection", response_model=MessageResponse)
def disconnect_docusign(current_user: CurrentUser, db: DbSession) -> MessageResponse:
    return DocusignService(db).disconnect(current_user)


@router.get("/consent-url", response_model=DocusignConsentUrlResponse)
def get_consent_url(current_user: CurrentUser, db: DbSession) -> DocusignConsentUrlResponse:
    return DocusignService(db).get_consent_url(current_user)


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
def list_envelopes(current_user: CurrentUser, db: DbSession) -> list[DocusignEnvelopeResponse]:
    return DocusignService(db).list_envelopes(current_user)


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
