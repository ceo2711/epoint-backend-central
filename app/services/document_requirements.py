"""Requisitos de documentación del onboarding con alternativas."""

from __future__ import annotations

from typing import Iterable

from app.models.document import Document
from app.models.enums import DocumentType, DocumentVerificationStatus

SSN_CARD = DocumentType.SSN_CARD.value
LICENSE_FRONT = DocumentType.DRIVERS_LICENSE_FRONT.value
LICENSE_BACK = DocumentType.DRIVERS_LICENSE_BACK.value
PASSPORT = DocumentType.PASSPORT.value
GREEN_CARD = DocumentType.GREEN_CARD.value
WORK_PERMIT = DocumentType.WORK_PERMIT.value
UTILITY_BILL = DocumentType.UTILITY_BILL.value
BANK_STATEMENT = DocumentType.BANK_STATEMENT.value

LICENSE_TYPES = (LICENSE_FRONT, LICENSE_BACK)
ALT_IDENTITY_TYPES = (PASSPORT, GREEN_CARD, WORK_PERMIT)
ADDRESS_TYPES = (UTILITY_BILL, BANK_STATEMENT)

ALL_UPLOADABLE_TYPES = (
    SSN_CARD,
    *LICENSE_TYPES,
    *ALT_IDENTITY_TYPES,
    *ADDRESS_TYPES,
)

IDENTITY_GAP_KEY = "IDENTITY_DOCUMENT"
ADDRESS_GAP_KEY = "ADDRESS_PROOF"

# Estados que exigen que el cliente vuelva a subir el documento: rechazado, o
# aprobado pero por vencer (no habilita el pase a LISTO_PARA_TRABAJAR).
REPLACEMENT_STATUSES = frozenset(
    {
        DocumentVerificationStatus.RECHAZADO.value,
        DocumentVerificationStatus.PROXIMO_A_VENCER.value,
    }
)


def _needs_replacement(doc: Document | None) -> bool:
    return doc is not None and doc.verification_status in REPLACEMENT_STATUSES


def _identity_path_options(uploaded: set[str]) -> list[frozenset[str]]:
    options: list[frozenset[str]] = []
    if LICENSE_FRONT in uploaded and LICENSE_BACK in uploaded:
        options.append(frozenset(LICENSE_TYPES))
    for doc_type in ALT_IDENTITY_TYPES:
        if doc_type in uploaded:
            options.append(frozenset({doc_type}))
    return options


def _address_path_options(uploaded: set[str]) -> list[frozenset[str]]:
    options: list[frozenset[str]] = []
    if UTILITY_BILL in uploaded:
        options.append(frozenset({UTILITY_BILL}))
    if BANK_STATEMENT in uploaded:
        options.append(frozenset({BANK_STATEMENT}))
    return options


def _path_is_approved(path: frozenset[str], by_type: dict[str, Document]) -> bool:
    return all(
        by_type.get(doc_type) is not None
        and by_type[doc_type].verification_status == DocumentVerificationStatus.APROBADO.value
        for doc_type in path
    )


def _path_is_clear_for_reminder(path: frozenset[str], by_type: dict[str, Document]) -> bool:
    """Subido y sin necesidad de reemplazo (aprobado o pendiente de revisión)."""
    for doc_type in path:
        doc = by_type.get(doc_type)
        if doc is None:
            return False
        if _needs_replacement(doc):
            return False
    return True


def _pick_identity_path(
    uploaded: set[str],
    by_type: dict[str, Document] | None = None,
) -> frozenset[str] | None:
    options = _identity_path_options(uploaded)
    if not options:
        return None
    if by_type is not None:
        for path in options:
            if _path_is_approved(path, by_type):
                return path
    return options[0]


def _pick_address_path(
    uploaded: set[str],
    by_type: dict[str, Document] | None = None,
) -> frozenset[str] | None:
    options = _address_path_options(uploaded)
    if not options:
        return None
    if by_type is not None:
        for path in options:
            if _path_is_approved(path, by_type):
                return path
    return options[0]


def resolve_required_upload_types(uploaded_types: Iterable[str]) -> set[str] | None:
    uploaded = set(uploaded_types)
    if SSN_CARD not in uploaded:
        return None
    identity = _pick_identity_path(uploaded)
    address = _pick_address_path(uploaded)
    if identity is None or address is None:
        return None
    return {SSN_CARD, *identity, *address}


def is_upload_requirement_met(uploaded_types: Iterable[str]) -> bool:
    return resolve_required_upload_types(uploaded_types) is not None


def document_upload_gaps(uploaded_types: Iterable[str]) -> list[str]:
    uploaded = set(uploaded_types)
    gaps: list[str] = []
    if SSN_CARD not in uploaded:
        gaps.append(SSN_CARD)
    if _pick_identity_path(uploaded) is None:
        if LICENSE_FRONT in uploaded and LICENSE_BACK not in uploaded:
            gaps.append(LICENSE_BACK)
        elif LICENSE_BACK in uploaded and LICENSE_FRONT not in uploaded:
            gaps.append(LICENSE_FRONT)
        else:
            gaps.append(IDENTITY_GAP_KEY)
    if _pick_address_path(uploaded) is None:
        gaps.append(ADDRESS_GAP_KEY)
    return gaps


def all_required_documents_approved(documents: list[Document]) -> bool:
    uploaded = {d.type for d in documents}
    by_type = {d.type: d for d in documents}
    if SSN_CARD not in uploaded:
        return False
    ssn = by_type.get(SSN_CARD)
    if ssn is None or ssn.verification_status != DocumentVerificationStatus.APROBADO.value:
        return False

    identity = _pick_identity_path(uploaded, by_type)
    address = _pick_address_path(uploaded, by_type)
    if identity is None or address is None:
        return False

    required = {SSN_CARD, *identity, *address}
    for doc_type in required:
        doc = by_type.get(doc_type)
        if doc is None or doc.verification_status != DocumentVerificationStatus.APROBADO.value:
            return False
    return True


def _pick_actionable_path(
    options: list[frozenset[str]],
    by_type: dict[str, Document],
    license_types: tuple[str, str] | None = None,
) -> frozenset[str] | None:
    """Ruta sobre la que el cliente debe actuar cuando ninguna está resuelta."""
    license_path = frozenset(license_types) if license_types else None
    non_license = [path for path in options if license_path is None or path != license_path]

    if license_types:
        front, back = license_types
        has_front = front in by_type
        has_back = back in by_type
        if has_front ^ has_back:
            return license_path

    for path in non_license:
        if all(by_type.get(doc_type) for doc_type in path):
            return path

    if license_path and license_path in options and all(doc_type in by_type for doc_type in license_path):
        rejected_on_path = [
            doc_type for doc_type in license_path if _needs_replacement(by_type[doc_type])
        ]
        if rejected_on_path:
            if non_license or len(rejected_on_path) == len(license_path):
                return None
            return license_path

    for path in options:
        if any(_needs_replacement(by_type.get(doc_type)) for doc_type in path):
            return path

    return options[0] if len(options) == 1 else None


def _category_reminder_gaps(
    uploaded: set[str],
    by_type: dict[str, Document],
    *,
    path_options_fn,
    group_gap_key: str,
    license_types: tuple[str, str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    options = path_options_fn(uploaded)
    for path in options:
        if _path_is_clear_for_reminder(path, by_type):
            return [], [], []

    missing: list[str] = []
    rejected: list[str] = []
    expiring: list[str] = []

    if not options:
        if license_types:
            front, back = license_types
            if front in uploaded and back not in uploaded:
                if _needs_replacement(by_type.get(front)):
                    missing.append(group_gap_key)
                    return missing, rejected, expiring
                missing.append(back)
                return missing, rejected, expiring
            if back in uploaded and front not in uploaded:
                if _needs_replacement(by_type.get(back)):
                    missing.append(group_gap_key)
                    return missing, rejected, expiring
                missing.append(front)
                return missing, rejected, expiring
        missing.append(group_gap_key)
        return missing, rejected, expiring

    active_path = _pick_actionable_path(options, by_type, license_types)
    if active_path is None:
        missing.append(group_gap_key)
        return missing, rejected, expiring

    for doc_type in active_path:
        doc = by_type.get(doc_type)
        if doc is None:
            missing.append(doc_type)
        elif doc.verification_status == DocumentVerificationStatus.RECHAZADO.value:
            rejected.append(doc_type)
        elif doc.verification_status == DocumentVerificationStatus.PROXIMO_A_VENCER.value:
            expiring.append(doc_type)

    return missing, rejected, expiring


def document_reminder_gaps(documents: list[Document]) -> tuple[list[str], list[str], list[str]]:
    """Pendientes reales para recordatorios: faltantes, rechazados y por vencer.

    Respeta las alternativas (licencia vs. pasaporte, utility bill vs. bank
    statement) y excluye las rutas que el cliente no está usando.
    """
    by_type = {doc.type: doc for doc in documents}
    uploaded = set(by_type.keys())
    missing: list[str] = []
    rejected: list[str] = []
    expiring: list[str] = []

    ssn = by_type.get(SSN_CARD)
    if ssn is None:
        missing.append(SSN_CARD)
    elif ssn.verification_status == DocumentVerificationStatus.RECHAZADO.value:
        rejected.append(SSN_CARD)
    elif ssn.verification_status == DocumentVerificationStatus.PROXIMO_A_VENCER.value:
        expiring.append(SSN_CARD)

    for path_options_fn, group_gap_key, license_types in (
        (_identity_path_options, IDENTITY_GAP_KEY, LICENSE_TYPES),
        (_address_path_options, ADDRESS_GAP_KEY, None),
    ):
        cat_missing, cat_rejected, cat_expiring = _category_reminder_gaps(
            uploaded,
            by_type,
            path_options_fn=path_options_fn,
            group_gap_key=group_gap_key,
            license_types=license_types,
        )
        missing.extend(cat_missing)
        rejected.extend(cat_rejected)
        expiring.extend(cat_expiring)

    return missing, rejected, expiring


def build_documents_status_for_context(
    documents: list[Document],
    *,
    type_labels: dict[str, str],
) -> dict:
    uploaded = {d.type for d in documents}
    by_type = {d.type: d for d in documents}
    required = resolve_required_upload_types(uploaded)

    def slot(doc_type: str) -> dict:
        doc = by_type.get(doc_type)
        if doc is None:
            return {
                "tipo": type_labels.get(doc_type, doc_type),
                "codigo": doc_type,
                "subido": False,
                "estado_verificacion": "FALTANTE",
            }
        return {
            "tipo": type_labels.get(doc_type, doc_type),
            "codigo": doc_type,
            "subido": True,
            "estado_verificacion": doc.verification_status,
        }

    identity_alternatives = [
        {
            "opcion": "Licencia de conducir (frente y dorso)",
            "documentos": [slot(LICENSE_FRONT), slot(LICENSE_BACK)],
            "completa": LICENSE_FRONT in uploaded and LICENSE_BACK in uploaded,
        },
        {
            "opcion": "Pasaporte",
            "documentos": [slot(PASSPORT)],
            "completa": PASSPORT in uploaded,
        },
        {
            "opcion": "Green Card",
            "documentos": [slot(GREEN_CARD)],
            "completa": GREEN_CARD in uploaded,
        },
        {
            "opcion": "Permiso de trabajo",
            "documentos": [slot(WORK_PERMIT)],
            "completa": WORK_PERMIT in uploaded,
        },
    ]
    address_alternatives = [
        {
            "opcion": "Utility Bill",
            "documentos": [slot(UTILITY_BILL)],
            "completa": UTILITY_BILL in uploaded,
        },
        {
            "opcion": "Bank Statement",
            "documentos": [slot(BANK_STATEMENT)],
            "completa": BANK_STATEMENT in uploaded,
        },
    ]

    extra_types = sorted(t for t in uploaded if t not in ALL_UPLOADABLE_TYPES)

    return {
        "ssn": slot(SSN_CARD),
        "identidad": {
            "instruccion": "Subí licencia (frente y dorso) O una alternativa si no tenés licencia.",
            "opciones": identity_alternatives,
            "completa": _pick_identity_path(uploaded) is not None,
        },
        "comprobante_domicilio": {
            "instruccion": "Subí Utility Bill O Bank Statement si no tenés factura de servicios.",
            "opciones": address_alternatives,
            "completa": _pick_address_path(uploaded) is not None,
        },
        "requeridos_activos": sorted(required) if required else [],
        "documentacion_completa": required is not None,
        "tipos_extra": extra_types,
    }
