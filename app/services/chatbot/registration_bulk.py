"""Parse structured multi-client registration messages for the chatbot."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import ClientSource
from app.services.chatbot.registration_options import resolve_merchant_id, resolve_source

BLOCK_HEADER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:datos\s+personales|personal\s+data)\s*:?\s*(?:\n|$)",
    re.IGNORECASE,
)
FULL_NAME_PATTERN = re.compile(
    r"(?:nombre\s+completo|full\s+name)\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
EMAIL_LABEL_PATTERN = re.compile(r"email\s*:\s*(\S+)", re.IGNORECASE)
PHONE_LABEL_PATTERN = re.compile(
    r"(?:n[uú]mero\s+de\s+(?:tel[eé]fono|telefono)|phone(?:\s+number)?|tel[eé]fono|telefono)\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
MERCHANT_LABEL_PATTERN = re.compile(
    r"(?:merchant|comercio|empresa)\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)
SOURCE_LABEL_PATTERN = re.compile(
    r"(?:fuente|source)\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


@dataclass
class ParsedRegistrationBlock:
    display_name: str
    draft: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _has_registration_fields(text: str) -> bool:
    return bool(FULL_NAME_PATTERN.search(text) or EMAIL_LABEL_PATTERN.search(text))


def _split_blocks(message: str) -> list[str]:
    text = message.strip()
    if not text:
        return []

    if BLOCK_HEADER_PATTERN.search(text):
        parts = re.split(
            r"(?=(?:^|\n)\s*(?:datos\s+personales|personal\s+data)\s*:?\s*(?:\n|$))",
            text,
            flags=re.IGNORECASE,
        )
        blocks = [part.strip() for part in parts if part.strip() and _has_registration_fields(part)]
        if blocks:
            return blocks

    name_label_count = len(re.findall(r"(?:nombre\s+completo|full\s+name)\s*:", text, re.IGNORECASE))
    if name_label_count >= 2:
        parts = re.split(
            r"(?=(?:^|\n)\s*(?:nombre\s+completo|full\s+name)\s*:)",
            text,
            flags=re.IGNORECASE,
        )
        blocks = [part.strip() for part in parts if part.strip() and _has_registration_fields(part)]
        if blocks:
            return blocks

    if name_label_count == 1 and _has_registration_fields(text):
        return [text]

    return []


def split_full_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _parse_block(text: str, merchants: list) -> ParsedRegistrationBlock:
    full_name_match = FULL_NAME_PATTERN.search(text)
    full_name = full_name_match.group(1).strip() if full_name_match else ""
    first_name, last_name = split_full_name(full_name)
    display_name = full_name or first_name or "Cliente sin nombre"

    draft: dict[str, Any] = {}
    errors: list[str] = []

    if first_name:
        draft["first_name"] = first_name
    if last_name:
        draft["last_name"] = last_name
    elif first_name:
        errors.append("apellido")

    email_match = EMAIL_LABEL_PATTERN.search(text)
    if email_match:
        draft["email"] = email_match.group(1).strip().lower()

    phone_match = PHONE_LABEL_PATTERN.search(text)
    if phone_match:
        draft["phone"] = re.sub(r"\s+", "", phone_match.group(1).strip())

    source_match = SOURCE_LABEL_PATTERN.search(text)
    if source_match:
        source = resolve_source(source_match.group(1))
        if source:
            draft["source"] = source
    else:
        source = resolve_source(text)
        if source:
            draft["source"] = source
        else:
            draft["source"] = ClientSource.OTHER.value

    merchant_match = MERCHANT_LABEL_PATTERN.search(text)
    merchant_text = merchant_match.group(1).strip() if merchant_match else text
    merchant_id = resolve_merchant_id(merchant_text, merchants)
    if merchant_id:
        draft["merchant_id"] = merchant_id
    elif merchant_match:
        errors.append("comercio")

    if not draft.get("email"):
        errors.append("email")
    if not draft.get("phone"):
        errors.append("teléfono")
    if not draft.get("first_name"):
        errors.append("nombre")

    return ParsedRegistrationBlock(display_name=display_name, draft=draft, errors=errors)


def parse_bulk_registration_blocks(message: str, merchants: list) -> list[ParsedRegistrationBlock]:
    return [_parse_block(block, merchants) for block in _split_blocks(message)]


def looks_like_structured_registration_block(message: str) -> bool:
    return bool(_split_blocks(message))


def looks_like_bulk_registration(message: str) -> bool:
    return len(_split_blocks(message)) >= 2
