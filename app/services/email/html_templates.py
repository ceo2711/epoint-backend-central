"""Plantillas HTML generadas con React Email (npm run emails:build en frontend)."""

from __future__ import annotations

import html
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "html"


class EmailTemplateError(Exception):
    pass


@lru_cache(maxsize=16)
def _load_template(name: str) -> str:
    path = TEMPLATES_DIR / f"{name}.html"
    if not path.is_file():
        raise EmailTemplateError(f"Plantilla HTML no encontrada: {path}")
    return path.read_text(encoding="utf-8")


def render_html_template(name: str, **variables: str) -> str:
    """Sustituye placeholders {{KEY}} en la plantilla HTML."""
    content = _load_template(name)
    for key, value in variables.items():
        token = f"{{{{{key}}}}}"
        content = content.replace(token, str(value))
    return content


def pending_items_html(items: list[str]) -> str:
    """Lista de pendientes como bloques HTML para el recordatorio."""
    if not items:
        return (
            '<p style="margin:0;font-size:14px;color:#666;line-height:1.5;">'
            "No hay ítems pendientes."
            "</p>"
        )
    rows: list[str] = []
    for item in items:
        safe = html.escape(item)
        rows.append(
            f'<p style="margin:0 0 8px;font-size:14px;color:#333;line-height:1.5;">• {safe}</p>'
        )
    return "".join(rows)


def resolve_email_logo_url(
    *,
    email_logo_url: str,
    backend_public_url: str,
    api_prefix: str,
    portal_base_url: str,
) -> str:
    override = email_logo_url.strip()
    if override:
        return override.rstrip("/")

    backend_base = backend_public_url.strip().rstrip("/")
    if backend_base:
        prefix = api_prefix if api_prefix.startswith("/") else f"/{api_prefix}"
        return f"{backend_base}{prefix}/branding/logo"

    return f"{portal_base_url.rstrip('/')}/epoint-logo.png"


def logo_url_for_emails(settings: Settings) -> str:
    return resolve_email_logo_url(
        email_logo_url=settings.email_logo_url,
        backend_public_url=settings.backend_public_url,
        api_prefix=settings.api_prefix,
        portal_base_url=settings.portal_base_url,
    )
