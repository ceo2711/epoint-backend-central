"""Helpers for chatbot document and board upload flows."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.models.enums import DocumentType
from app.services.chatbot.context import DOCUMENT_TYPE_LABELS
from app.services.boards import BoardService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DOCUMENT_TYPE_ALIASES: dict[str, str] = {
    "ssn": DocumentType.SSN_CARD.value,
    "social security": DocumentType.SSN_CARD.value,
    "tarjeta ssn": DocumentType.SSN_CARD.value,
    "licencia frente": DocumentType.DRIVERS_LICENSE_FRONT.value,
    "licencia (frente)": DocumentType.DRIVERS_LICENSE_FRONT.value,
    "frente licencia": DocumentType.DRIVERS_LICENSE_FRONT.value,
    "drivers license front": DocumentType.DRIVERS_LICENSE_FRONT.value,
    "licencia dorso": DocumentType.DRIVERS_LICENSE_BACK.value,
    "licencia (dorso)": DocumentType.DRIVERS_LICENSE_BACK.value,
    "dorso licencia": DocumentType.DRIVERS_LICENSE_BACK.value,
    "drivers license back": DocumentType.DRIVERS_LICENSE_BACK.value,
    "utility bill": DocumentType.UTILITY_BILL.value,
    "factura de servicios": DocumentType.UTILITY_BILL.value,
    "utility": DocumentType.UTILITY_BILL.value,
    "bank statement": DocumentType.BANK_STATEMENT.value,
    "estado de cuenta": DocumentType.BANK_STATEMENT.value,
    "pasaporte": DocumentType.PASSPORT.value,
    "passport": DocumentType.PASSPORT.value,
    "green card": DocumentType.GREEN_CARD.value,
    "permiso de trabajo": DocumentType.WORK_PERMIT.value,
    "work permit": DocumentType.WORK_PERMIT.value,
}

UPLOAD_DOCUMENT_INTENT_PATTERN = re.compile(
    r"(?:quiero\s+)?(?:subir|cargar|enviar|adjuntar|upload|attach)(?:\s+(?:un|una|mi|el|la|a))?"
    r"(?:\s+)?(?:documento|documentos|archivo|archivos|licencia|ssn|factura|pasaporte|document|file)\b|"
    r"(?:i\s+)?(?:want\s+to\s+)?(?:upload|attach)(?:\s+(?:a|my|the))?\s+(?:document|file)\b",
    re.IGNORECASE,
)
UPLOAD_BOARD_INTENT_PATTERN = re.compile(
    r"(?:quiero\s+)?(?:subir|cargar|enviar|adjuntar|upload|attach)(?:\s+(?:un|una|el|la|a))?"
    r"(?:\s+)?(?:archivo|archivos|adjunto|adjuntos|imagen|foto|pdf|file|document)"
    r".*(?:tarjeta|tablero|tarea|card|board)\b|"
    r"(?:subir|cargar|adjuntar|upload|attach).*(?:en|a|al|to)\s+(?:la\s+)?(?:tarjeta|tarea|card)\b|"
    r"(?:attach|upload).*(?:to|on)\s+(?:a\s+)?(?:board\s+)?card\b",
    re.IGNORECASE,
)
CARD_REF_PATTERN = re.compile(
    r"(?:tarjeta|tarea|card)\s*#?(\d+)\b",
    re.IGNORECASE,
)


def document_type_label(document_type: str, locale: str) -> str:
    label = DOCUMENT_TYPE_LABELS.get(document_type, document_type)
    if locale.lower().startswith("en"):
        en_labels = {
            DocumentType.SSN_CARD.value: "SSN card",
            DocumentType.DRIVERS_LICENSE_FRONT.value: "Driver's license (front)",
            DocumentType.DRIVERS_LICENSE_BACK.value: "Driver's license (back)",
            DocumentType.UTILITY_BILL.value: "Utility bill",
            DocumentType.BANK_STATEMENT.value: "Bank statement",
            DocumentType.PASSPORT.value: "Passport",
            DocumentType.GREEN_CARD.value: "Green card",
            DocumentType.WORK_PERMIT.value: "Work permit",
        }
        return en_labels.get(document_type, document_type)
    return label


def list_document_type_options(locale: str) -> list[dict[str, str]]:
    return [
        {"value": doc_type.value, "label": document_type_label(doc_type.value, locale)}
        for doc_type in DocumentType
    ]


def resolve_document_type(message: str) -> str | None:
    stripped = message.strip()
    upper = stripped.upper().replace(" ", "_").replace("-", "_")
    for doc_type in DocumentType:
        if doc_type.value == upper or doc_type.value in upper:
            return doc_type.value

    lower = message.lower().strip()
    for alias, value in DOCUMENT_TYPE_ALIASES.items():
        if alias in lower:
            return value

    for doc_type in DocumentType:
        label = DOCUMENT_TYPE_LABELS.get(doc_type.value, "").lower()
        if label and label in lower:
            return doc_type.value

    return None


def list_board_card_options(db: Session, client_id: int) -> list[dict[str, str | int]]:
    board = BoardService(db).get_board_for_client(client_id)
    if board is None:
        return []

    options: list[dict[str, str | int]] = []
    for board_list in sorted(board.lists, key=lambda item: item.position):
        for card in sorted(board_list.cards, key=lambda item: item.position):
            options.append(
                {
                    "id": card.id,
                    "title": card.title,
                    "column": board_list.title,
                    "status": card.status,
                }
            )
    return options


def resolve_board_card_id(message: str, cards: list[dict[str, str | int]]) -> int | None:
    match = CARD_REF_PATTERN.search(message)
    if match:
        candidate = int(match.group(1))
        if any(card["id"] == candidate for card in cards):
            return candidate

    lower = message.lower()
    for card in cards:
        title = str(card["title"]).lower()
        if title and title in lower:
            return int(card["id"])
    return None
