from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMBase


class ClientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)


class ClientUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=30)


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
    rejection_reason: str | None
    rejected_at: datetime | None
    approved_at: datetime | None
    date_of_birth: date | None
    has_ssn: bool = False
    registered_by_user_id: int
    created_at: datetime


class ClientDetailResponse(ClientResponse):
    addresses: list["AddressResponse"] = []
    vehicles: list["VehicleResponse"] = []
    documents: list["DocumentBrief"] = []


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
    ssn: str | None = Field(default=None, min_length=9, max_length=11)
    date_of_birth: date | None = None


class DocumentBrief(ORMBase):
    id: int
    type: str
    verification_status: str
    original_filename: str
    expires_at: date | None
    uploaded_at: datetime


class ClientApproveResponse(BaseModel):
    client: ClientResponse
    temp_password: str
