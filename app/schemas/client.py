from datetime import date, datetime
import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import ClientSource
from app.schemas.common import ORMBase


class MerchantBrief(ORMBase):
    id: int
    code: str
    name: str


class ClientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    source: ClientSource
    merchant_id: int


class ClientUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=30)
    source: ClientSource | None = None
    merchant_id: int | None = None


class ClientReject(BaseModel):
    reason: str = Field(min_length=5)


class ClientApprove(BaseModel):
    advisor_user_id: int


class ClientConflict(BaseModel):
    client_id: int
    client_name: str
    client_email: str


class ClientAvailabilityResponse(BaseModel):
    available: bool
    email: ClientConflict | None = None
    phone: ClientConflict | None = None


class AdvisorBrief(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str


class ClientResponse(ORMBase):
    id: int
    status: str
    first_name: str
    last_name: str
    email: str
    phone: str
    source: str | None
    merchant: MerchantBrief | None = None
    rejection_reason: str | None
    rejected_at: datetime | None
    approved_at: datetime | None
    date_of_birth: date | None
    has_ssn: bool = False
    registered_by_user_id: int
    created_at: datetime


class ClientDetailResponse(ClientResponse):
    has_portal_access: bool = False
    portal_email: str | None = None
    portal_login_url: str | None = None
    addresses: list["AddressResponse"] = []
    vehicles: list["VehicleResponse"] = []
    documents: list["DocumentBrief"] = []


class ClientPortalPasswordResponse(BaseModel):
    email: str
    temp_password: str
    portal_login_url: str


class AddressCreate(BaseModel):
    type: str = Field(pattern="^(CURRENT|PREVIOUS)$")
    street: str
    city: str
    state: str
    zip_code: str
    residence_since_month: int | None = Field(default=None, ge=1, le=12)
    residence_since_year: int | None = Field(default=None, ge=1900, le=2100)


class AddressResponse(ORMBase):
    id: int
    type: str
    street: str
    city: str
    state: str
    zip_code: str
    residence_since_month: int | None
    residence_since_year: int | None


class VehicleCreate(BaseModel):
    order: int = Field(ge=1, le=2)
    model: str
    year: int = Field(ge=1900, le=2100)
    color: str


class VehicleResponse(ORMBase):
    id: int
    order: int
    model: str
    year: int
    color: str


class ProfileUpdate(BaseModel):
    ssn: str | None = Field(default=None, max_length=11)
    date_of_birth: date | None = None

    @field_validator("ssn", mode="before")
    @classmethod
    def normalize_ssn(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return None if not stripped else stripped
        return value

    @field_validator("ssn")
    @classmethod
    def validate_ssn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = re.sub(r"\D", "", value)
        if len(digits) != 9:
            raise ValueError("El número de Seguro Social debe tener 9 dígitos (formato XXX-XX-XXXX).")
        return digits


class ClientSsnResponse(BaseModel):
    ssn: str


class LocalizedStringList(BaseModel):
    en: list[str] = Field(default_factory=list)
    es: list[str] = Field(default_factory=list)


class DocumentBrief(ORMBase):
    id: int
    type: str
    verification_status: str
    original_filename: str
    expires_at: date | None
    uploaded_at: datetime
    mime_type: str | None = None
    download_url: str | None = None
    rejection_reasons: LocalizedStringList | None = None
    approval_reasons: LocalizedStringList | None = None


class ClientApproveResponse(BaseModel):
    client: ClientResponse
    temp_password: str


class ClientStatsResponse(BaseModel):
    pending_review: int
    approved_in_onboarding: int
    rejected: int
    onboarding_in_progress: int
    completed: int
    total: int
