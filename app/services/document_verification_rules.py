"""Reglas de aprobación/rechazo para verificación IA de documentos."""

from __future__ import annotations

from typing import Any

IDENTITY_DOCUMENT_TYPES = frozenset(
    {
        "SSN_CARD",
        "DRIVERS_LICENSE_FRONT",
        "DRIVERS_LICENSE_BACK",
        "PASSPORT",
        "GREEN_CARD",
        "WORK_PERMIT",
    }
)

ADDRESS_PROOF_TYPES = frozenset({"UTILITY_BILL", "BANK_STATEMENT"})

WRONG_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "SSN_CARD": (
        "invoice",
        "receipt",
        "statement",
        "bank",
        "utility",
        "bill",
        "stripe",
        "report",
        "executive",
        "contract",
        "proposal",
        "presentation",
        "slide",
        "tax",
        "w-2",
        "1099",
        "payroll",
        "license",
        "passport",
    ),
    "DRIVERS_LICENSE_FRONT": ("invoice", "ssn", "social security", "statement", "receipt", "passport"),
    "DRIVERS_LICENSE_BACK": ("invoice", "ssn", "social security", "statement", "receipt", "passport"),
}

DOCUMENT_TYPE_GUIDANCE: dict[str, dict[str, str]] = {
    "SSN_CARD": {
        "description": (
            "A physical or scanned US Social Security card issued by the SSA. "
            "It must show 'Social Security' / SSA branding, the cardholder's name, "
            "and a 9-digit Social Security Number (XXX-XX-XXXX, partial masking allowed)."
        ),
        "reject_examples": (
            "invoices, receipts, bank statements, utility bills, tax forms, reports, "
            "screenshots of unrelated apps, driver's licenses, passports, or any non-SSN document."
        ),
    },
    "DRIVERS_LICENSE_FRONT": {
        "description": (
            "The front side of a government-issued driver's license with photo, name, "
            "license number, and expiration date visible."
        ),
        "reject_examples": "SSN cards, invoices, any document that is not the front of a driver's license.",
    },
    "DRIVERS_LICENSE_BACK": {
        "description": (
            "The back side of a government-issued driver's license with barcode/MRZ "
            "and reverse-side information."
        ),
        "reject_examples": "front of license, SSN cards, invoices, unrelated documents.",
    },
    "PASSPORT": {
        "description": "A passport identity page with photo, name, passport number, and nationality.",
        "reject_examples": "invoices, SSN cards, driver's licenses, unrelated documents.",
    },
    "GREEN_CARD": {
        "description": "A US Permanent Resident Card (Green Card) with photo, name, and USCIS number.",
        "reject_examples": "invoices, SSN cards, unrelated documents.",
    },
    "WORK_PERMIT": {
        "description": "A US work authorization document (EAD/work permit) with photo, name, and validity dates.",
        "reject_examples": "invoices, SSN cards, unrelated documents.",
    },
    "UTILITY_BILL": {
        "description": (
            "A recent utility bill (electric, gas, water, internet, etc.) showing the client's "
            "full name and service address."
        ),
        "reject_examples": "SSN cards, driver's licenses, invoices unrelated to utilities.",
    },
    "BANK_STATEMENT": {
        "description": (
            "A recent bank account statement showing the client's full name and mailing/residential address."
        ),
        "reject_examples": "SSN cards, utility bills, unrelated financial reports.",
    },
}


def requires_name_match(document_type: str) -> bool:
    return document_type in IDENTITY_DOCUMENT_TYPES or document_type in ADDRESS_PROOF_TYPES


def build_document_type_context(document_type: str, client_name: str) -> str:
    guidance = DOCUMENT_TYPE_GUIDANCE.get(
        document_type,
        {
            "description": f"The specific document type requested: {document_type}.",
            "reject_examples": "any document that is not exactly the requested type.",
        },
    )
    return (
        f"Expected upload slot: {document_type}.\n"
        f"Client full name: {client_name}.\n"
        f"Required document: {guidance['description']}\n"
        f"REJECT (document_type_matches=false) if the file is any of: {guidance['reject_examples']}\n"
        "document_type_matches must be false when the content is a different document category, "
        "even if the image/PDF is readable and in color."
    )


def _detected_type_conflicts(document_type: str, result: dict[str, Any]) -> bool:
    """Rechaza cuando la IA aprueba el tipo pero la etiqueta detectada indica otro documento."""
    if result.get("document_type_matches") is not True:
        return False
    detected = str(result.get("detected_document_type", "")).strip().lower()
    if not detected:
        return False
    keywords = WRONG_TYPE_KEYWORDS.get(document_type, ())
    return any(keyword in detected for keyword in keywords)


def is_verification_approved(result: dict[str, Any], document_type: str) -> bool:
    """Fail-closed: solo aprueba cuando todos los criterios obligatorios son True explícito."""
    if _detected_type_conflicts(document_type, result):
        return False

    approved = (
        result.get("is_readable") is True
        and result.get("is_complete") is True
        and result.get("is_color") is True
        and result.get("corners_cut") is False
        and result.get("is_expired") is False
        and result.get("document_type_matches") is True
    )

    if requires_name_match(document_type):
        approved = approved and result.get("name_matches") is True

    if document_type in ADDRESS_PROOF_TYPES:
        approved = approved and result.get("address_matches") is True

    return approved
