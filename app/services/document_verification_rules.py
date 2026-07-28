"""Reglas de aprobación/rechazo para verificación IA de documentos."""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
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

# Solo IDs con fecha de vencimiento real. SSN y comprobantes de domicilio no usan is_expired.
EXPIRABLE_DOCUMENT_TYPES = frozenset(
    {
        "DRIVERS_LICENSE_FRONT",
        "DRIVERS_LICENSE_BACK",
        "PASSPORT",
        "GREEN_CARD",
        "WORK_PERMIT",
    }
)

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

_NAME_SOFT_MATCH_RULE = (
    "name_matches: set true when the client's identity is clearly the same person even if "
    "middle names are abbreviated/omitted, initials are used, or there are minor OCR typos "
    "(e.g. Eliangi vs Eliangli, Liduvina vs L). Require at least a recognizable first name "
    "and last surname. Set false only when the name on the document is clearly a different person."
)

DOCUMENT_TYPE_GUIDANCE: dict[str, dict[str, str]] = {
    "SSN_CARD": {
        "description": (
            "A physical or scanned US Social Security card issued by the SSA. "
            "It must show 'Social Security' / SSA branding, the cardholder's name, "
            "and a 9-digit Social Security Number (XXX-XX-XXXX, partial masking allowed). "
            "IMPORTANT: Social Security cards do NOT expire. Always set is_expired=false "
            "and expires_at=null. Do not invent expiration dates from issue dates, "
            "signatures, or other printed numbers."
        ),
        "reject_examples": (
            "invoices, receipts, bank statements, utility bills, tax forms, reports, "
            "screenshots of unrelated apps, driver's licenses, passports, or any non-SSN document."
        ),
        "expiry_rule": (
            "SSN cards never expire. Set is_expired=false and expires_at=null always."
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
            "and reverse-side information. The holder's printed name is usually NOT on this side."
        ),
        "reject_examples": "front of license, SSN cards, invoices, unrelated documents.",
        "name_rule": (
            "Do NOT require the client's name to be visible on this side. "
            "Set name_matches=true when the image is clearly the back of a driver's license."
        ),
    },
    "PASSPORT": {
        "description": (
            "A passport identity page with photo, name, passport number, and nationality. "
            "Accepted as an alternative to a driver's license when the client does not have one."
        ),
        "reject_examples": "invoices, SSN cards, unrelated documents.",
    },
    "GREEN_CARD": {
        "description": (
            "A US Permanent Resident Card (Green Card) with photo, name, and USCIS number. "
            "Accepted as an alternative to a driver's license when the client does not have one."
        ),
        "reject_examples": "invoices, SSN cards, unrelated documents.",
    },
    "WORK_PERMIT": {
        "description": (
            "A US work authorization document (EAD/work permit) with photo, name, and validity dates. "
            "Accepted as an alternative to a driver's license when the client does not have one."
        ),
        "reject_examples": "invoices, SSN cards, unrelated documents.",
    },
    "UTILITY_BILL": {
        "description": (
            "A utility bill (electric, gas, water, internet, etc.) showing the client's "
            "name and service address. Bills from roughly the last 90 days relative to today "
            "are acceptable. Billing-period / meter-read / due dates that fall before or near "
            "today are NOT 'future' and must NOT be rejected as expired."
        ),
        "reject_examples": "SSN cards, driver's licenses, invoices unrelated to utilities.",
        "expiry_rule": (
            "Utility bills do not use ID-style expiration. Always set is_expired=false and "
            "expires_at=null. Do not reject solely because a due date or meter reading looks "
            "'in the future' relative to an outdated calendar — compare only against Today's date."
        ),
        "name_rule": _NAME_SOFT_MATCH_RULE,
    },
    "BANK_STATEMENT": {
        "description": (
            "A bank account statement showing the client's name and mailing/residential address. "
            "Statements from roughly the last 90 days relative to today are acceptable. "
            "Accepted as an alternative to a Utility Bill."
        ),
        "reject_examples": "SSN cards, unrelated financial reports.",
        "expiry_rule": (
            "Bank statements do not use ID-style expiration. Always set is_expired=false and "
            "expires_at=null. Compare statement dates only against Today's date."
        ),
        "name_rule": _NAME_SOFT_MATCH_RULE,
    },
}


def requires_name_match(document_type: str) -> bool:
    if document_type == "DRIVERS_LICENSE_BACK":
        return False
    return document_type in IDENTITY_DOCUMENT_TYPES or document_type in ADDRESS_PROOF_TYPES


def build_document_type_context(
    document_type: str,
    client_name: str,
    *,
    today: date | None = None,
) -> str:
    guidance = DOCUMENT_TYPE_GUIDANCE.get(
        document_type,
        {
            "description": f"The specific document type requested: {document_type}.",
            "reject_examples": "any document that is not exactly the requested type.",
        },
    )
    today_iso = (today or date.today()).isoformat()
    extra_rules = ""
    if guidance.get("name_rule"):
        extra_rules += f"\n{guidance['name_rule']}"
    elif requires_name_match(document_type):
        extra_rules += f"\n{_NAME_SOFT_MATCH_RULE}"
    if guidance.get("expiry_rule"):
        extra_rules += f"\n{guidance['expiry_rule']}"
    return (
        f"Today's date (use this as ground truth for 'recent' / 'future'): {today_iso}.\n"
        f"Expected upload slot: {document_type}.\n"
        f"Client full name: {client_name}.\n"
        f"Also return detected_name with the name printed on the document (or null).\n"
        f"Required document: {guidance['description']}\n"
        f"REJECT (document_type_matches=false) if the file is any of: {guidance['reject_examples']}\n"
        "document_type_matches must be false when the content is a different document category, "
        "even if the image/PDF is readable and in color."
        + extra_rules
    )


def document_can_expire(document_type: str) -> bool:
    """True solo para documentos con fecha de vencimiento real (licencias, pasaporte, etc.)."""
    return document_type in EXPIRABLE_DOCUMENT_TYPES


def _tokenize_name(name: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-ZáéíóúñüÁÉÍÓÚÑÜ\s-]", " ", name or "")
    return [part.lower() for part in re.split(r"[\s-]+", cleaned) if len(part) > 1]


def _tokens_close(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 2:
        return SequenceMatcher(None, a, b).ratio() >= 0.86
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def names_roughly_match(client_name: str, detected_name: str | None) -> bool:
    """Acepta abreviaturas de segundo nombre y typos OCR leves (p. ej. Eliangi/Eliangli)."""
    if not detected_name or not str(detected_name).strip():
        return False
    client_tokens = _tokenize_name(client_name)
    detected_tokens = _tokenize_name(str(detected_name))
    if len(client_tokens) < 2 or len(detected_tokens) < 2:
        return False
    if _tokens_close(client_tokens[0], detected_tokens[0]) and _tokens_close(
        client_tokens[-1], detected_tokens[-1]
    ):
        return True
    significant = [token for token in client_tokens if len(token) > 2]
    if not significant:
        return False
    return all(any(_tokens_close(token, other) for other in detected_tokens) for token in significant)


def _extract_detected_name(result: dict[str, Any]) -> str | None:
    raw = result.get("detected_name")
    if isinstance(raw, str) and raw.strip() and raw.strip().lower() not in {"null", "none", "n/a"}:
        return raw.strip()
    # Fallback: nombre entre comillas en motivos de rechazo de la IA.
    blob = " ".join(
        str(item.get("en", "") if isinstance(item, dict) else item)
        for item in (result.get("rejection_reasons") or [])
    )
    match = re.search(r"['\"]([A-Za-zÁÉÍÓÚÑáéíóúñüÜ][^'\"]{2,80})['\"]", blob)
    if match:
        return match.group(1).strip()
    return None


def normalize_verification_result(
    result: dict[str, Any],
    document_type: str,
    *,
    client_name: str | None = None,
) -> dict[str, Any]:
    """Corrige alucinaciones conocidas de la IA antes de aplicar reglas de aprobación."""
    normalized = dict(result)
    if not document_can_expire(document_type):
        normalized["is_expired"] = False
        normalized["expires_at"] = None

    if requires_name_match(document_type) and normalized.get("name_matches") is not True and client_name:
        detected = _extract_detected_name(normalized)
        if names_roughly_match(client_name, detected):
            normalized["name_matches"] = True

    return normalized


def _detected_type_conflicts(document_type: str, result: dict[str, Any]) -> bool:
    """Rechaza cuando la IA aprueba el tipo pero la etiqueta detectada indica otro documento."""
    if result.get("document_type_matches") is not True:
        return False
    detected = str(result.get("detected_document_type", "")).strip().lower()
    if not detected:
        return False
    keywords = WRONG_TYPE_KEYWORDS.get(document_type, ())
    return any(keyword in detected for keyword in keywords)


def is_verification_approved(
    result: dict[str, Any],
    document_type: str,
    *,
    client_name: str | None = None,
) -> bool:
    """Fail-closed: solo aprueba cuando todos los criterios obligatorios son True explícito."""
    result = normalize_verification_result(result, document_type, client_name=client_name)

    if _detected_type_conflicts(document_type, result):
        return False

    approved = (
        result.get("is_readable") is True
        and result.get("is_complete") is True
        and result.get("is_color") is True
        and result.get("corners_cut") is False
        and result.get("document_type_matches") is True
    )
    if document_can_expire(document_type):
        approved = approved and result.get("is_expired") is False

    if requires_name_match(document_type):
        approved = approved and result.get("name_matches") is True

    if document_type in ADDRESS_PROOF_TYPES:
        approved = approved and result.get("address_matches") is True

    return approved
