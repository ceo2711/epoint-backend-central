from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import ClientSource, ProspectStatus
from app.schemas.common import ORMBase

class ProspectCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    source: ClientSource | None = None
    merchant_id: int
    initial_status: ProspectStatus = Field(
        description="Debe ser LEAD_CALIFICADO o LEAD_NO_CALIFICADO",
    )
    notes: str | None = None


class ProspectUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=30)
    source: ClientSource | None = None
    notes: str | None = None


class ProspectStatusUpdate(BaseModel):
    status: ProspectStatus
    note: str | None = Field(default=None, max_length=2000)


class ProspectHistoryNote(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class ProspectMarkContacted(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ProspectLinkCalendlyEvent(BaseModel):
    calendly_event_id: int


class ProspectLinkEnvelope(BaseModel):
    envelope_id: int


class ProspectLinkPaymentLink(BaseModel):
    payment_link_id: int


class ProspectAssignSalesRep(BaseModel):
    assigned_to_user_id: int


class SalesRepBrief(ORMBase):
    id: int
    first_name: str
    last_name: str
    email: str


class ProspectCalendlyBrief(ORMBase):
    id: int
    name: str
    status: str
    start_time: datetime
    end_time: datetime
    invitee_name: str | None = None
    invitee_email: str | None = None
    meeting_url: str | None = None
    event_type_name: str | None = None


class ProspectEnvelopeBrief(ORMBase):
    id: int
    subject: str
    status: str
    signer_name: str
    signer_email: str
    sent_at: datetime
    completed_at: datetime | None = None


class ProspectPaymentBrief(ORMBase):
    id: int
    amount: Decimal
    currency: str
    status: str
    payment_url: str
    paid_at: datetime | None = None
    created_at: datetime


class ProspectHistoryResponse(ORMBase):
    id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    note: str | None
    changed_by_user_id: int
    created_at: datetime
    changed_by_name: str | None = None


class ProspectResponse(ORMBase):
    id: int
    merchant_id: int
    assigned_to_user_id: int
    status: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    phone: str
    source: str | None
    notes: str | None
    converted_client_id: int | None
    calendly_event_id: int | None
    docusign_envelope_id: int | None
    payment_link_id: int | None
    created_at: datetime
    updated_at: datetime
    assigned_to: SalesRepBrief | None = None
    merchant_name: str | None = None


class ProspectDetailResponse(ProspectResponse):
    history: list[ProspectHistoryResponse] = Field(default_factory=list)
    calendly_event: ProspectCalendlyBrief | None = None
    docusign_envelope: ProspectEnvelopeBrief | None = None
    docusign_envelopes: list[ProspectEnvelopeBrief] = Field(default_factory=list)
    payment_link: ProspectPaymentBrief | None = None


class ProspectConvertResponse(BaseModel):
    prospect_id: int
    client_id: int
    message: str
