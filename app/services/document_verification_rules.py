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

# Solo IDs con fecha de vencimiento real en el lado que se verifica.
# El dorso de la licencia casi nunca muestra EXP; no usar is_expired ahí.
EXPIRABLE_DOCUMENT_TYPES = frozenset(
    {
        "DRIVERS_LICENSE_FRONT",
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

# Si la etiqueta detectada confirma el tipo esperado, no rechazar por menciones
# secundarias (p. ej. "license back with ssn card underneath").
EXPECTED_TYPE_POSITIVE_HINTS: dict[str, tuple[str, ...]] = {
    "DRIVERS_LICENSE_FRONT": (
        "license front",
        "driver license",
        "driver's license",
        "drivers license",
        "dl front",
        "front of",
        "id card",
        "state id",
    ),
    "DRIVERS_LICENSE_BACK": (
        "license back",
        "driver license back",
        "driver's license back",
        "drivers license back",
        "driver license",
        "dl back",
        "back of",
        "barcode",
        "pdf417",
        "mrz",
        "reverse",
        "dorso",
    ),
    "SSN_CARD": ("social security", "ssn card", "ssn", "ssa"),
    "UTILITY_BILL": (
        "utility",
        "electric",
        "gas",
        "water",
        "internet",
        "cable",
        "bill",
        "statement of account",
    ),
    "BANK_STATEMENT": ("bank statement", "account statement", "checking", "savings"),
}

_NAME_SOFT_MATCH_RULE = (
    "name_matches: Prefer APPROVING. Set true when it is plausibly the same person — "
    "middle names may be abbreviated/omitted, initials are fine, and minor OCR typos are OK "
    "(e.g. Eliangi vs Eliangli). Matching first name + one surname is enough. "
    "Set false ONLY when the printed name is clearly a different person."
)

_QUALITY_SOFT_RULE = (
    "Quality bias (IMPORTANT): phone photos are imperfect. Prefer APPROVING when the primary "
    "document type is correct, key fields are readable enough, AND the document is flat/"
    "centered with no hands. "
    "Set is_complete=true unless large parts of the PRIMARY document are missing from the frame. "
    "Set is_color=true for normal phone/camera photos (do not reject for slight color cast, "
    "flash, or near-grayscale scans of a color card). "
    "Set corners_cut=false unless a major corner of the PRIMARY document is clearly cropped out. "
    "Background clutter, shadows, glare, or another paper behind must NOT cause rejection. "
    "Hands, fingers, thumbs, or fingernails ARE a hard reject — not background clutter."
)

_PRESENTATION_HARD_RULE = (
    "Presentation (HARD REJECT): Place the document flat and centered. "
    "Set hands_visible=true if any hand, finger, thumb, fingernail, or skin is holding or "
    "covering the document — even if every printed field is perfectly readable and matches. "
    "Set is_centered=false if the document is held up, taken as a selfie, or is not the "
    "centered subject. A readable SSN held between fingers MUST be rejected. "
    "Ask the client to photograph the document from above on a flat surface, or upload a clean scan."
)

DOCUMENT_TYPE_GUIDANCE: dict[str, dict[str, str]] = {
    "SSN_CARD": {
        "description": (
            "A physical or scanned US Social Security card issued by the SSA. "
            "It must show 'Social Security' / SSA branding, the cardholder's name, "
            "and a 9-digit Social Security Number (XXX-XX-XXXX, partial masking allowed). "
            "The card must be flat and centered in the photo/scan — no hands or fingers. "
            "IMPORTANT: Social Security cards do NOT expire. Always set is_expired=false "
            "and expires_at=null. Do not invent expiration dates from issue dates, "
            "signatures, or other printed numbers."
        ),
        "reject_examples": (
            "invoices, receipts, bank statements, utility bills, tax forms, reports, "
            "screenshots of unrelated apps, driver's licenses, passports, any non-SSN document, "
            "or an SSN card held in a hand / with fingers or a thumb visible on the card."
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
            "and reverse-side information. The holder's printed name is usually NOT on this side. "
            "Judge the DOMINANT primary subject in the frame: if the license back (barcode/MRZ) "
            "is clearly the main document, approve even when another paper is partially visible "
            "underneath or in the background."
        ),
        "reject_examples": (
            "photos whose PRIMARY subject is the front of a license, an SSN card, an invoice, "
            "or any other document that is not a driver's license back."
        ),
        "name_rule": (
            "Do NOT require the client's name to be visible on this side. "
            "Set name_matches=true when the image is clearly the back of a driver's license."
        ),
        "expiry_rule": (
            "Driver's license backs usually do not show expiration. "
            "Set is_expired=false and expires_at=null unless a clear expiration date is visible "
            "and already past Today's date. Never invent an expiration date."
        ),
        "complete_rule": (
            "is_complete=true when the license back is visible enough to confirm barcode/MRZ "
            "or reverse-side layout. Background clutter or another sheet underneath does NOT "
            "make the document incomplete. corners_cut=true only if the primary license corners "
            "are cropped out of the photo."
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
            "A utility bill (electric, gas, water, internet, cable, etc.) or similar "
            "service statement showing a customer name and a service/mailing address. "
            "Bills from roughly the last year relative to today are acceptable. "
            "Screenshots and PDF downloads from the provider portal are OK."
        ),
        "reject_examples": "SSN cards, driver's licenses, random invoices unrelated to utilities/services.",
        "expiry_rule": (
            "Utility bills do not use ID-style expiration. Always set is_expired=false and "
            "expires_at=null. Do not reject for due dates, billing periods, or meter reads."
        ),
        "name_rule": _NAME_SOFT_MATCH_RULE,
        "address_rule": (
            "address_matches: Prefer true when any residential/service address is visible. "
            "Do not require an exact street-by-street match to a known profile address."
        ),
    },
    "BANK_STATEMENT": {
        "description": (
            "A bank account statement showing the client's name and a mailing/residential address. "
            "Statements from roughly the last year relative to today are acceptable. "
            "Accepted as an alternative to a Utility Bill. Screenshots/PDFs are OK."
        ),
        "reject_examples": "SSN cards, unrelated financial marketing reports.",
        "expiry_rule": (
            "Bank statements do not use ID-style expiration. Always set is_expired=false and "
            "expires_at=null. Compare statement dates only against Today's date."
        ),
        "name_rule": _NAME_SOFT_MATCH_RULE,
        "address_rule": (
            "address_matches: Prefer true when any mailing/residential address is visible."
        ),
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
    if guidance.get("complete_rule"):
        extra_rules += f"\n{guidance['complete_rule']}"
    if guidance.get("address_rule"):
        extra_rules += f"\n{guidance['address_rule']}"
    extra_rules += f"\n{_QUALITY_SOFT_RULE}"
    extra_rules += f"\n{_PRESENTATION_HARD_RULE}"
    return (
        f"Today's date (use this as ground truth for 'recent' / 'future'): {today_iso}.\n"
        f"Expected upload slot: {document_type}.\n"
        f"Client full name: {client_name}.\n"
        f"Also return detected_name with the name printed on the document (or null).\n"
        f"Required document: {guidance['description']}\n"
        f"REJECT (document_type_matches=false) ONLY if the PRIMARY subject is clearly one of: "
        f"{guidance['reject_examples']}\n"
        "When the primary document looks like the required type, set document_type_matches=true "
        "and prefer approving. Ignore secondary papers underneath or in the background."
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
    # Más permisivo: typos OCR leves y truncados
    if a.startswith(b) or b.startswith(a):
        shorter = min(len(a), len(b))
        if shorter >= 3:
            return True
    if abs(len(a) - len(b)) > 3:
        return SequenceMatcher(None, a, b).ratio() >= 0.8
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def names_roughly_match(client_name: str, detected_name: str | None) -> bool:
    """Acepta abreviaturas, un apellido y typos OCR leves."""
    if not detected_name or not str(detected_name).strip():
        return False
    client_tokens = _tokenize_name(client_name)
    detected_tokens = _tokenize_name(str(detected_name))
    if not client_tokens or not detected_tokens:
        return False

    # Primer nombre cercano + algún apellido significativo del cliente
    if _tokens_close(client_tokens[0], detected_tokens[0]):
        surnames = [token for token in client_tokens[1:] if len(token) > 2]
        if not surnames:
            return True
        if any(
            any(_tokens_close(surname, other) for other in detected_tokens)
            for surname in surnames
        ):
            return True

    if len(client_tokens) < 2 or len(detected_tokens) < 1:
        return False
    if _tokens_close(client_tokens[0], detected_tokens[0]) and _tokens_close(
        client_tokens[-1], detected_tokens[-1]
    ):
        return True
    significant = [token for token in client_tokens if len(token) > 2]
    if not significant:
        return False
    # Soft: al menos la mitad de los tokens significativos aparecen
    hits = sum(
        1 for token in significant if any(_tokens_close(token, other) for other in detected_tokens)
    )
    return hits >= max(1, (len(significant) + 1) // 2)


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

    # Calidad suave: si el tipo es correcto y se lee, no tumbar por color/esquinas/complete.
    if (
        normalized.get("document_type_matches") is True
        and normalized.get("is_readable") is True
    ):
        normalized["is_complete"] = True
        normalized["is_color"] = True
        normalized["corners_cut"] = False
        if document_type in ADDRESS_PROOF_TYPES and normalized.get("name_matches") is True:
            # Dirección visible "suficiente"; no exigir match exacto de calle.
            normalized["address_matches"] = True

    return normalized


def _has_presentation_issue(result: dict[str, Any], document_type: str) -> bool:
    """Rechaza fotos con manos o documentos de identidad que no están centrados."""
    if result.get("hands_visible") is True:
        return True
    if document_type in IDENTITY_DOCUMENT_TYPES and result.get("is_centered") is False:
        return True
    return False


def _detected_type_conflicts(document_type: str, result: dict[str, Any]) -> bool:
    """Rechaza cuando la IA aprueba el tipo pero la etiqueta detectada indica otro documento.

    No rechaza si la etiqueta también confirma el tipo esperado (evita falsos positivos
    cuando Gemini menciona un papel de fondo, p. ej. 'license back with ssn underneath').
    """
    if result.get("document_type_matches") is not True:
        return False
    detected = str(result.get("detected_document_type", "")).strip().lower()
    if not detected:
        return False
    positive_hints = EXPECTED_TYPE_POSITIVE_HINTS.get(document_type, ())
    if positive_hints and any(hint in detected for hint in positive_hints):
        return False
    keywords = WRONG_TYPE_KEYWORDS.get(document_type, ())
    return any(keyword in detected for keyword in keywords)


def is_verification_approved(
    result: dict[str, Any],
    document_type: str,
    *,
    client_name: str | None = None,
) -> bool:
    """Aprueba con criterios suaves: tipo correcto + legible (+ nombre/vencimiento cuando aplica)."""
    result = normalize_verification_result(result, document_type, client_name=client_name)

    if _detected_type_conflicts(document_type, result):
        return False
    if _has_presentation_issue(result, document_type):
        return False

    approved = (
        result.get("is_readable") is True
        and result.get("document_type_matches") is True
    )
    if document_can_expire(document_type):
        approved = approved and result.get("is_expired") is False

    if requires_name_match(document_type):
        approved = approved and result.get("name_matches") is True

    return approved