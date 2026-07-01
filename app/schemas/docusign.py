from datetime import datetime, timezone

from pydantic import BaseModel, EmailStr, Field


class DocusignConnectionResponse(BaseModel):
    connected: bool
    account_id: str | None = None
    account_name: str | None = None
    impersonated_user_email: str | None = None
    auth_server: str | None = None
    default_template_id: str | None = None
    default_template_role_name: str | None = None
    connected_at: datetime | None = None


class DocusignConnectRequest(BaseModel):
    integration_key: str = Field(min_length=10, max_length=64)
    impersonated_user_id: str = Field(min_length=10, max_length=64)
    account_id: str = Field(min_length=10, max_length=64)
    private_key: str = Field(min_length=100)
    auth_server: str = Field(default="account-d.docusign.com", max_length=120)
    default_template_id: str | None = Field(default=None, max_length=64)
    default_template_role_name: str = Field(default="Signer", max_length=120)


class DocusignConsentUrlResponse(BaseModel):
    consent_url: str
    redirect_uri: str


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
    sent_by_user_id: int
    sent_by_name: str | None = None
    sent_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocusignSendEnvelopeResponse(BaseModel):
    envelope: DocusignEnvelopeResponse
    message: str = "Contrato enviado correctamente"
