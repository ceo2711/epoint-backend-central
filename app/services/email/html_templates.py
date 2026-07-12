"""Plantillas HTML generadas con React Email (npm run emails:build en frontend)."""

from __future__ import annotations

import html
from functools import lru_cache
from pathlib import Path

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


def logo_url_for_emails(frontend_base_url: str) -> str:
    base = frontend_base_url.rstrip("/")
    return f"{base}/epoint-logo.png"
