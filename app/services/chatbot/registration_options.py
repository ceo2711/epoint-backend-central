"""Source and merchant helpers for chatbot client registration."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.models.enums import ClientSource

if TYPE_CHECKING:
    from app.models.merchant import Merchant

SOURCE_LABELS: dict[ClientSource, tuple[str, str]] = {
    ClientSource.WEB_PAGE: ("Página web", "Website"),
    ClientSource.WHATSAPP: ("WhatsApp", "WhatsApp"),
    ClientSource.FACEBOOK: ("Facebook", "Facebook"),
    ClientSource.INSTAGRAM: ("Instagram", "Instagram"),
    ClientSource.REFERRAL: ("Referido", "Referral"),
    ClientSource.PHONE_CALL: ("Llamada telefónica", "Phone call"),
    ClientSource.INFLUENCERS: ("Influencers", "Influencers"),
    ClientSource.OTHER: ("Otro", "Other"),
}

SOURCE_ALIASES: dict[ClientSource, tuple[str, ...]] = {
    ClientSource.WEB_PAGE: ("pagina web", "página web", "sitio web", "website", "web", "pagina", "página"),
    ClientSource.WHATSAPP: ("whatsapp", "wsp", "wa"),
    ClientSource.FACEBOOK: ("facebook", "fb"),
    ClientSource.INSTAGRAM: ("instagram", "ig"),
    ClientSource.REFERRAL: ("referido", "referral", "recomendacion", "recomendación"),
    ClientSource.PHONE_CALL: ("llamada", "telefono", "teléfono", "phone call", "phone"),
    ClientSource.INFLUENCERS: ("influencer", "influencers", "creador", "creadores"),
    ClientSource.OTHER: ("otro", "other", "otra"),
}


def source_label(source: ClientSource | str, locale: str) -> str:
    try:
        enum_val = ClientSource(source) if isinstance(source, str) else source
    except ValueError:
        return str(source)
    es, en = SOURCE_LABELS[enum_val]
    return en if locale.lower().startswith("en") else es


def format_source_options(locale: str) -> str:
    lines: list[str] = []
    for source in ClientSource:
        label = source_label(source, locale)
        lines.append(f"- **{label}** (`{source.value}`)")
    return "\n".join(lines)


def format_merchant_options(locale: str, merchants: list[Merchant]) -> str:
    if not merchants:
        return (
            "No hay comercios activos configurados."
            if not locale.lower().startswith("en")
            else "No active merchants are configured."
        )
    lines: list[str] = []
    for merchant in merchants:
        lines.append(f"- **{merchant.name}** (`{merchant.code}`)")
    return "\n".join(lines)


def resolve_source(message: str) -> str | None:
    lower = message.lower()
    for source in ClientSource:
        if source.value.lower() in lower:
            return source.value
        es_label, en_label = SOURCE_LABELS[source]
        if es_label.lower() in lower or en_label.lower() in lower:
            return source.value
        for alias in SOURCE_ALIASES.get(source, ()):
            if alias in lower:
                return source.value
    return None


PHONE_ONLY_PATTERN = re.compile(r"^\+?[\d][\d\s\-()]{7,}[\d]$")


def resolve_merchant_id(message: str, merchants: list[Merchant]) -> int | None:
    stripped = message.strip()
    lower = stripped.lower()
    if PHONE_ONLY_PATTERN.fullmatch(stripped):
        return None

    id_match = re.search(
        r"(?:comercio|merchant|empresa)\s*#?(\d+)\b",
        lower,
    )
    if id_match:
        candidate = int(id_match.group(1))
        if any(m.id == candidate for m in merchants):
            return candidate

    for merchant in merchants:
        code = merchant.code.lower()
        name = merchant.name.lower()
        if code in lower or name in lower:
            return merchant.id
        if any(part in lower for part in name.split() if len(part) > 3):
            return merchant.id
    return None
