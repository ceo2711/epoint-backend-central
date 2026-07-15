from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import ClientSource


class DocusignConnectionResponse(BaseModel):
    connected: bool
    account_id: str | None = None
    default_template_id: str | None = None
    default_template_role_name: str | None = None
    auth_server: str | None = None


class DocusignConsentUrlResponse(BaseModel):
    consent_url: str
    redirect_uri: str


class DocusignWebhookUrlResponse(BaseModel):
    webhook_url: str
    connect_hmac_configured: bool
    instructions: str


class DocusignTemplateResponse(BaseModel):
    template_id: str
    name: str
    description: str | None = None


class DocusignTemplateRoleResponse(BaseModel):
    role_name: str
    recipient_type: str | None = None


class DocusignTemplateDetailResponse(DocusignTemplateResponse):
    roles: list[DocusignTemplateRoleResponse] = Field(default_factory=list)


class DocusignSendEnvelopeRequest(BaseModel):
    signer_name: str = Field(min_length=1, max_length=255)
    signer_email: EmailStr
    template_id: str | None = Field(default=None, max_length=64)
    template_role_name: str | None = Field(default=None, max_length=120)
    subject: str = Field(default="Contrato ePoint — Firma requerida", max_length=255)
    client_id: int | None = None
    prospect_id: int | None = None
    text_tabs: dict[str, str] | None = None


class DocusignEnvelopeResponse(BaseModel):
    id: int
    docusign_envelope_id: str
    signer_name: str
    signer_email: str
    template_id: str
    template_role_name: str
    subject: str
    status: str
    client_id: int | None = None
    client_name: str | None = None
    prospect_id: int | None = None
    sent_by_user_id: int
    sent_by_name: str | None = None
    sent_at: datetime
    completed_at: datetime | None = None
    has_signed_document: bool = False
    can_register_client: bool = False
    client_registered: bool = False

    model_config = {"from_attributes": True}


class DocusignSendEnvelopeResponse(BaseModel):
    envelope: DocusignEnvelopeResponse
    message: str = "Contrato enviado correctamente"


class DocusignRegisterClientRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    source: ClientSource
    merchant_id: int


class DocusignRegisterClientResponse(BaseModel):
    envelope: DocusignEnvelopeResponse
    client_id: int
    message: str = "Cliente registrado y enviado a revisión de onboarding"
