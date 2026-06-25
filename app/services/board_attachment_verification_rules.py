"""Reglas de verificación IA para adjuntos del tablero (reportes Equifax, etc.)."""

from __future__ import annotations

from typing import Any

BoardAttachmentKind = str

CREDIT_BUREAU_REPORTS = "CREDIT_BUREAU_REPORTS"
EXPERIAN_CREDIT_REPORT = "EXPERIAN_CREDIT_REPORT"
EQUIFAX_CREDIT_REPORT = "EQUIFAX_CREDIT_REPORT"
TRANSUNION_CREDIT_REPORT = "TRANSUNION_CREDIT_REPORT"
CLARITY_REPORT = "CLARITY_REPORT"
GENERIC_BOARD_UPLOAD = "GENERIC_BOARD_UPLOAD"

BUREAU_KINDS = frozenset(
    {
        CREDIT_BUREAU_REPORTS,
        EXPERIAN_CREDIT_REPORT,
        EQUIFAX_CREDIT_REPORT,
        TRANSUNION_CREDIT_REPORT,
    }
)

ATTACHMENT_KIND_GUIDANCE: dict[str, dict[str, str]] = {
    CREDIT_BUREAU_REPORTS: {
        "description": (
            "A consumer credit report PDF or clear screenshot downloaded from Experian, Equifax, or TransUnion. "
            "Must show bureau branding, the consumer's name, and credit account/tradeline information. "
            "Acceptable sources: experian.com, equifax.com, transunion.com official consumer portals."
        ),
        "reject_examples": (
            "invoices, bank statements, utility bills, SSN cards, driver's licenses, random PDFs, "
            "marketing emails, tutorials, blank pages, or reports from ChexSystems/Innovis/Clarity only."
        ),
        "bureau_rule": (
            "The file must be a legitimate consumer credit report from Experian, Equifax, OR TransUnion "
            "(any one of the three is acceptable for this card)."
        ),
    },
    EXPERIAN_CREDIT_REPORT: {
        "description": (
            "An Experian consumer credit report or Experian accounts/tradelines view showing Experian branding, "
            "the consumer's name, and account details."
        ),
        "reject_examples": (
            "Equifax-only reports, TransUnion-only reports, invoices, unrelated documents."
        ),
        "bureau_rule": "detected_bureau must be Experian.",
    },
    EQUIFAX_CREDIT_REPORT: {
        "description": (
            "An Equifax consumer credit report or Equifax accounts/tradelines view showing Equifax branding, "
            "the consumer's name, and account details (balances, account numbers, status)."
        ),
        "reject_examples": (
            "Experian-only reports, TransUnion-only reports, invoices, unrelated documents, "
            "screenshots without Equifax branding."
        ),
        "bureau_rule": "detected_bureau must be Equifax.",
    },
    TRANSUNION_CREDIT_REPORT: {
        "description": (
            "A TransUnion consumer credit report or TransUnion accounts/tradelines view showing TransUnion branding, "
            "the consumer's name, and account details."
        ),
        "reject_examples": (
            "Experian-only reports, Equifax-only reports, invoices, unrelated documents."
        ),
        "bureau_rule": "detected_bureau must be TransUnion.",
    },
    CLARITY_REPORT: {
        "description": (
            "A consumer report from Experian Clarity Services (clarityservices.com) showing Clarity/Experian branding "
            "and the consumer's personal/report data."
        ),
        "reject_examples": (
            "standard bureau reports without Clarity branding, invoices, unrelated documents."
        ),
        "bureau_rule": "detected_bureau should be Clarity or Experian Clarity Services.",
    },
    GENERIC_BOARD_UPLOAD: {
        "description": (
            "A document or image related to the board task. Must be readable and appear to match the card context."
        ),
        "reject_examples": "blank files, corrupted files, completely unrelated content.",
        "bureau_rule": "",
    },
}


def resolve_attachment_kind(*, card_title: str, list_title: str, requires_file_upload: bool) -> BoardAttachmentKind:
    title = card_title.strip().lower()
    column = list_title.strip().lower()

    if "reportes" in title and ("equifax" in title or "experian" in title or "transunion" in title):
        return CREDIT_BUREAU_REPORTS
    if "clarity" in title:
        return CLARITY_REPORT

    if column == "equifax":
        return EQUIFAX_CREDIT_REPORT
    if column == "experian":
        return EXPERIAN_CREDIT_REPORT
    if column in {"transunion", "trans union"}:
        return TRANSUNION_CREDIT_REPORT

    if requires_file_upload:
        return GENERIC_BOARD_UPLOAD

    return GENERIC_BOARD_UPLOAD


def build_board_attachment_context(
    *,
    attachment_kind: str,
    client_name: str,
    card_title: str,
    list_title: str,
) -> str:
    guidance = ATTACHMENT_KIND_GUIDANCE.get(attachment_kind, ATTACHMENT_KIND_GUIDANCE[GENERIC_BOARD_UPLOAD])
    bureau_line = guidance.get("bureau_rule")
    bureau_section = f"\nBureau rule: {bureau_line}" if bureau_line else ""

    return (
        f"Board card: {card_title}\n"
        f"Board column: {list_title}\n"
        f"Expected upload kind: {attachment_kind}\n"
        f"Client full name: {client_name}\n"
        f"Required document: {guidance['description']}\n"
        f"REJECT (document_type_matches=false) if the file is any of: {guidance['reject_examples']}\n"
        "document_type_matches must be false when the content is a different document category, "
        "even if the PDF/image is readable."
        f"{bureau_section}\n"
        "name_matches: true only if the client's full name (or a clear partial match) appears on the report."
    )


def _expected_bureau(attachment_kind: str) -> str | None:
    mapping = {
        EXPERIAN_CREDIT_REPORT: "experian",
        EQUIFAX_CREDIT_REPORT: "equifax",
        TRANSUNION_CREDIT_REPORT: "transunion",
        CLARITY_REPORT: "clarity",
    }
    return mapping.get(attachment_kind)


def _bureau_matches(result: dict[str, Any], attachment_kind: str) -> bool:
    if attachment_kind == CREDIT_BUREAU_REPORTS:
        detected = str(result.get("detected_bureau", "")).strip().lower()
        if not detected:
            return result.get("document_type_matches") is True
        return any(b in detected for b in ("experian", "equifax", "transunion"))

    expected = _expected_bureau(attachment_kind)
    if not expected:
        return True

    detected = str(result.get("detected_bureau", "")).strip().lower()
    if not detected:
        return result.get("document_type_matches") is True
    return expected in detected


def is_board_attachment_approved(result: dict[str, Any], attachment_kind: str) -> bool:
    """Fail-closed: aprueba solo cuando todos los criterios obligatorios son True explícito."""
    approved = (
        result.get("is_readable") is True
        and result.get("is_complete") is True
        and result.get("document_type_matches") is True
        and result.get("name_matches") is True
    )

    if attachment_kind in BUREAU_KINDS or attachment_kind == CLARITY_REPORT:
        approved = approved and result.get("is_recent") is True
        approved = approved and _bureau_matches(result, attachment_kind)
    else:
        approved = approved and result.get("is_recent") is not False

    return approved
