"""Análisis de datos y documentos pendientes del onboarding."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus, DocumentVerificationStatus
from app.models.vehicle import Vehicle
from app.services.document_requirements import (
    ADDRESS_GAP_KEY,
    IDENTITY_GAP_KEY,
    document_upload_gaps,
)

REMINDER_ELIGIBLE_STATUSES = frozenset(
    {
        ClientStatus.APROBADO_PARA_ONBOARDING.value,
        ClientStatus.EN_CARGA_DATOS.value,
        ClientStatus.DOCUMENTOS_EN_REVISION.value,
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

PROFILE_FIELD_LABELS_ES: dict[str, str] = {
    "ssn": "SSN / Seguro Social",
    "date_of_birth": "Fecha de nacimiento",
    "address": "Dirección actual",
    "vehicle": "Datos del vehículo",
}


@dataclass(slots=True)
class OnboardingReminderGaps:
    profile_items: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    rejected_documents: list[str] = field(default_factory=list)

    @property
    def needs_reminder(self) -> bool:
        return bool(self.profile_items or self.missing_documents or self.rejected_documents)

    def all_pending_labels(self) -> list[str]:
        items = list(self.profile_items)
        items.extend(self.missing_documents)
        items.extend(self.rejected_documents)
        return items


def _document_label(doc_type: str) -> str:
    return DOCUMENT_TYPE_LABELS_ES.get(doc_type, doc_type.replace("_", " ").title())


def analyze_onboarding_gaps(db: Session, client: Client) -> OnboardingReminderGaps:
    gaps = OnboardingReminderGaps()

    if not client.ssn_encrypted:
        gaps.profile_items.append(PROFILE_FIELD_LABELS_ES["ssn"])
    if not client.date_of_birth:
        gaps.profile_items.append(PROFILE_FIELD_LABELS_ES["date_of_birth"])

    current_addr = db.execute(
        select(Address).where(Address.client_id == client.id, Address.type == "CURRENT")
    ).scalar_one_or_none()
    if current_addr is None:
        gaps.profile_items.append(PROFILE_FIELD_LABELS_ES["address"])

    vehicle = db.execute(
        select(Vehicle).where(Vehicle.client_id == client.id, Vehicle.order == 1)
    ).scalar_one_or_none()
    if vehicle is None:
        gaps.profile_items.append(PROFILE_FIELD_LABELS_ES["vehicle"])

    documents = list(
        db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
    )
    uploaded_types = {doc.type for doc in documents}

    for gap_type in document_upload_gaps(uploaded_types):
        gaps.missing_documents.append(_document_label(gap_type))

    for doc in documents:
        if doc.verification_status == DocumentVerificationStatus.RECHAZADO.value:
            gaps.rejected_documents.append(
                f"{_document_label(doc.type)} (rechazado — volver a subir)"
            )

    return gaps


def client_needs_onboarding_reminder(db: Session, client: Client) -> bool:
    if client.status not in REMINDER_ELIGIBLE_STATUSES:
        return False
    if not client.approved_at:
        return False
    return analyze_onboarding_gaps(db, client).needs_reminder
