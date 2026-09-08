"""Análisis de datos y documentos pendientes del onboarding."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus
from app.models.role import Role
from app.models.user import User
from app.services.document_requirements import (
    ADDRESS_GAP_KEY,
    IDENTITY_GAP_KEY,
    document_reminder_gaps,
)

REMINDER_ELIGIBLE_STATUSES = frozenset(
    {
        ClientStatus.APROBADO_PARA_ONBOARDING.value,
        ClientStatus.EN_CARGA_DATOS.value,
        ClientStatus.DOCUMENTOS_EN_REVISION.value,
    }
)

REMINDER_EXCLUDED_STATUSES = frozenset(
    {
        ClientStatus.PENDIENTE_DE_REVISION.value,
        ClientStatus.RECHAZADO.value,
        ClientStatus.INACTIVO.value,
    }
)

DOCUMENT_TYPE_LABELS_ES: dict[str, str] = {
    "SSN_CARD": "Tarjeta SSN",
    "DRIVERS_LICENSE_FRONT": "Licencia (frente)",
    "DRIVERS_LICENSE_BACK": "Licencia (dorso)",
    "UTILITY_BILL": "Utility Bill",
    "BANK_STATEMENT": "Bank Statement",
    "PASSPORT": "Pasaporte",
    "GREEN_CARD": "Green Card",
    "WORK_PERMIT": "Permiso de trabajo",
    IDENTITY_GAP_KEY: (
        "Documento de identidad (licencia frente y dorso, pasaporte, green card o permiso de trabajo)"
    ),
    ADDRESS_GAP_KEY: "Comprobante de domicilio (Utility Bill o Bank Statement)",
}

DOCUMENT_TYPE_LABELS_EN: dict[str, str] = {
    "SSN_CARD": "SSN card",
    "DRIVERS_LICENSE_FRONT": "Driver's license (front)",
    "DRIVERS_LICENSE_BACK": "Driver's license (back)",
    "UTILITY_BILL": "Utility bill",
    "BANK_STATEMENT": "Bank statement",
    "PASSPORT": "Passport",
    "GREEN_CARD": "Green card",
    "WORK_PERMIT": "Work permit",
    IDENTITY_GAP_KEY: (
        "Identity document (driver's license front and back, passport, green card, or work permit)"
    ),
    ADDRESS_GAP_KEY: "Proof of address (utility bill or bank statement)",
}

PROFILE_FIELD_LABELS_ES: dict[str, str] = {
    "ssn": "SSN / Seguro Social",
    "date_of_birth": "Fecha de nacimiento",
    "address": "Dirección actual",
    "previous_address": "Dirección anterior",
}

PROFILE_FIELD_LABELS_EN: dict[str, str] = {
    "ssn": "SSN / Social Security Number",
    "date_of_birth": "Date of birth",
    "address": "Current address",
    "previous_address": "Previous address",
}

REJECTED_SUFFIX_ES = " (rechazado — volver a subir)"
REJECTED_SUFFIX_EN = " (rejected — please re-upload)"

EXPIRING_SUFFIX_ES = " (vence pronto — subir uno vigente)"
EXPIRING_SUFFIX_EN = " (expiring soon — please upload a valid one)"


@dataclass(slots=True)
class OnboardingReminderGaps:
    profile_keys: list[str] = field(default_factory=list)
    profile_items: list[str] = field(default_factory=list)
    missing_document_keys: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    rejected_document_keys: list[str] = field(default_factory=list)
    rejected_documents: list[str] = field(default_factory=list)
    expiring_document_keys: list[str] = field(default_factory=list)
    expiring_documents: list[str] = field(default_factory=list)

    @property
    def needs_reminder(self) -> bool:
        return bool(
            self.profile_items
            or self.missing_documents
            or self.rejected_documents
            or self.expiring_documents
        )

    def all_pending_labels(self, *, locale: str = "es") -> list[str]:
        items = list(self.profile_items)
        items.extend(self.missing_documents)
        items.extend(self.rejected_documents)
        items.extend(self.expiring_documents)
        return items


def _normalize_locale(locale: str | None) -> str:
    if locale and locale.lower().startswith("en"):
        return "en"
    return "es"


def _document_labels(locale: str) -> dict[str, str]:
    if locale == "en":
        return DOCUMENT_TYPE_LABELS_EN
    return DOCUMENT_TYPE_LABELS_ES


def _profile_labels(locale: str) -> dict[str, str]:
    if locale == "en":
        return PROFILE_FIELD_LABELS_EN
    return PROFILE_FIELD_LABELS_ES


def _document_label(doc_type: str, locale: str = "es") -> str:
    labels = _document_labels(locale)
    return labels.get(doc_type, doc_type.replace("_", " ").title())


def _rejected_label(doc_type: str, locale: str = "es") -> str:
    suffix = REJECTED_SUFFIX_EN if locale == "en" else REJECTED_SUFFIX_ES
    return f"{_document_label(doc_type, locale)}{suffix}"


def _expiring_label(doc_type: str, locale: str = "es") -> str:
    suffix = EXPIRING_SUFFIX_EN if locale == "en" else EXPIRING_SUFFIX_ES
    return f"{_document_label(doc_type, locale)}{suffix}"


def analyze_onboarding_gaps(db: Session, client: Client, *, locale: str = "es") -> OnboardingReminderGaps:
    locale = _normalize_locale(locale)
    profile_labels = _profile_labels(locale)
    gaps = OnboardingReminderGaps()

    if not client.ssn_encrypted:
        gaps.profile_keys.append("ssn")
    if not client.date_of_birth:
        gaps.profile_keys.append("date_of_birth")

    current_addr = db.execute(
        select(Address).where(Address.client_id == client.id, Address.type == "CURRENT")
    ).scalar_one_or_none()
    if current_addr is None:
        gaps.profile_keys.append("address")
    else:
        from app.services.residence import residence_less_than_two_years

        if residence_less_than_two_years(
            current_addr.residence_since_month,
            current_addr.residence_since_year,
        ):
            previous_addr = db.execute(
                select(Address).where(Address.client_id == client.id, Address.type == "PREVIOUS")
            ).scalar_one_or_none()
            if previous_addr is None or not (previous_addr.street and previous_addr.city):
                gaps.profile_keys.append("previous_address")

    # El vehículo es opcional: onboarding puede cargarlo después a mano.
    gaps.profile_items = [profile_labels[key] for key in gaps.profile_keys]

    documents = list(
        db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
    )
    missing_types, rejected_types, expiring_types = document_reminder_gaps(documents)

    for gap_type in missing_types:
        gaps.missing_document_keys.append(gap_type)
        gaps.missing_documents.append(_document_label(gap_type, locale))

    for doc_type in rejected_types:
        gaps.rejected_document_keys.append(doc_type)
        gaps.rejected_documents.append(_rejected_label(doc_type, locale))

    for doc_type in expiring_types:
        gaps.expiring_document_keys.append(doc_type)
        gaps.expiring_documents.append(_expiring_label(doc_type, locale))

    return gaps


def get_active_portal_user(db: Session, client_id: int) -> User | None:
    return db.execute(
        select(User)
        .join(Role)
        .where(
            User.client_id == client_id,
            Role.code == "CLIENT",
            User.is_active.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()


def fetch_clients_with_active_portal_user(db: Session) -> list[tuple[Client, User]]:
    rows = db.execute(
        select(Client, User)
        .join(User, (User.client_id == Client.id) & User.is_active.is_(True))
        .join(Role, Role.id == User.role_id)
        .where(
            Client.status.in_(REMINDER_ELIGIBLE_STATUSES),
            Client.status.not_in(REMINDER_EXCLUDED_STATUSES),
            Client.approved_at.is_not(None),
            Role.code == "CLIENT",
        )
        .order_by(Client.id)
    ).unique().all()
    return [(client, portal_user) for client, portal_user in rows]


def client_needs_onboarding_reminder(db: Session, client: Client) -> bool:
    if client.status in REMINDER_EXCLUDED_STATUSES:
        return False
    if client.status not in REMINDER_ELIGIBLE_STATUSES:
        return False
    if not client.approved_at:
        return False
    if get_active_portal_user(db, client.id) is None:
        return False
    return analyze_onboarding_gaps(db, client).needs_reminder
