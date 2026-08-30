from datetime import date, datetime
import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMBase
from app.schemas.prospect import ProspectPipelineSummary


class MerchantBrief(ORMBase):
    id: int
    code: str
    name: str
    sede_id: int | None = None


class ClientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    source: str = Field(min_length=1, max_length=40)
    merchant_id: int


class ClientUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=30)
    source: str | None = Field(default=None, max_length=40)
    merchant_id: int | None = None
    date_of_birth: date | None = None
    ssn: str | None = Field(default=None, max_length=11)

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


class ClientReject(BaseModel):
    reason: str = Field(min_length=5)


class ClientApprove(BaseModel):
    """Body vacío (compat). El asesor se asigna al pasar a Listo para trabajar."""

    advisor_user_id: int | None = None


class ClientAssignAdvisor(BaseModel):
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


class ClientSignedContractBrief(BaseModel):
    envelope_id: int
    signed_at: datetime
    subject: str
    has_document: bool = False


class ClientResponse(ORMBase):
    id: int
    status: str
    is_qualified: bool = True
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
    registered_by: AdvisorBrief | None = None
    advisor: AdvisorBrief | None = None
    advisors: list[AdvisorBrief] = Field(default_factory=list)
    created_at: datetime
    docusign_contract_signed_at: datetime | None = None
    signed_contract: ClientSignedContractBrief | None = None
    board_unlocked: bool = Field(
        default=False,
        description="True cuando el cliente ya puede ver/usar el tablero del portal",
    )
    has_unread_inbound_email: bool = False

class ClientDetailResponse(ClientResponse):
    has_portal_access: bool = False
    portal_email: str | None = None
    portal_login_url: str | None = None
    portal_temp_password: str | None = None
    addresses: list["AddressResponse"] = []
    vehicles: list["VehicleResponse"] = []
    documents: list["DocumentBrief"] = []
    source_prospect: ProspectPipelineSummary | None = None


class ClientPortalPasswordResponse(BaseModel):
    email: str
    temp_password: str
    portal_login_url: str


def _calendar_year_not_future(value: int | None) -> int | None:
    if value is None:
        return None
    this_year = date.today().year
    if value < 1900 or value > this_year:
        raise ValueError(f"El año debe estar entre 1900 y {this_year}")
    return value


class AddressCreate(BaseModel):
    type: str = Field(pattern="^(CURRENT|PREVIOUS)$")
    street: str
    city: str
    state: str
    zip_code: str
    residence_since_month: int | None = Field(default=None, ge=1, le=12)
    residence_since_year: int | None = Field(default=None, ge=1900, le=2100)

    @field_validator("residence_since_year")
    @classmethod
    def residence_year_not_future(cls, value: int | None) -> int | None:
        return _calendar_year_not_future(value)


class AddressResponse(ORMBase):
    id: int
    type: str
    street: str
    city: str
    state: str
    zip_code: str
    residence_since_month: int | None
    residence_since_year: int | None


class AddressSuggestion(BaseModel):
    place_id: str
    description: str
    main_text: str
    secondary_text: str
    # Vienen completos cuando el proveedor resuelve la dirección en la misma llamada;
    # si están vacíos, el cliente debe pedir /addresses/details.
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""


class AddressAutocompleteResponse(BaseModel):
    suggestions: list[AddressSuggestion] = []


class AddressDetailsResponse(BaseModel):
    place_id: str
    formatted_address: str
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""


class VehicleCreate(BaseModel):
    order: int = Field(ge=1, le=2)
    model: str
    year: int = Field(ge=1900, le=2100)
    color: str
    license_plate: str | None = Field(default=None, max_length=20)

    @field_validator("year")
    @classmethod
    def vehicle_year_not_future(cls, value: int) -> int:
        return _calendar_year_not_future(value) or value

    @field_validator("license_plate", mode="before")
    @classmethod
    def normalize_license_plate(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().upper()
            return None if not stripped else stripped
        return value


class VehicleResponse(ORMBase):
    id: int
    order: int
    model: str
    year: int
    color: str
    license_plate: str | None = None


class ProfileUpdate(BaseModel):
    ssn: str | None = Field(default=None, max_length=11)
    date_of_birth: date | None = None
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return None if not stripped else stripped
        return value

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

    @field_validator("date_of_birth")
    @classmethod
    def date_of_birth_reasonable(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = date.today()
        if value > today:
            raise ValueError("La fecha de nacimiento no puede ser futura")
        oldest = date(today.year - 120, today.month, today.day)
        if value.year < 1900 or value < oldest:
            raise ValueError("La fecha de nacimiento no es válida")
        return value


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


class ClientBulkDeleteRequest(BaseModel):
    client_ids: list[int] = Field(min_length=1, max_length=100)


class ClientBulkDeleteFailure(BaseModel):
    client_id: int
    reason: str


class ClientBulkDeleteResponse(BaseModel):
    deleted_ids: list[int]
    failures: list[ClientBulkDeleteFailure] = Field(default_factory=list)
