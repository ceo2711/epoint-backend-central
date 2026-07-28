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


def _is_local_url(url: str) -> bool:
    lower = url.lower()
    return "localhost" in lower or "127.0.0.1" in lower


def resolve_branding_asset_url(
    *,
    slug: str,
    backend_public_url: str,
    api_prefix: str,
    portal_base_url: str,
    email_logo_url: str = "",
) -> str:
    """URL pública de un asset de branding (logo / badges) para emails."""
    filename_by_slug = {
        "logo": "epoint-logo.png",
        "google-play-badge": "google-play-badge.png",
        "app-store-badge": "app-store-badge.png",
    }
    filename = filename_by_slug.get(slug)
    if not filename:
        raise ValueError(f"Asset de branding desconocido: {slug}")

    prefix = api_prefix if api_prefix.startswith("/") else f"/{api_prefix}"
    backend_base = backend_public_url.strip().rstrip("/")
    if backend_base and not _is_local_url(backend_base):
        return f"{backend_base}{prefix}/branding/{slug if slug != 'logo' else 'logo'}"

    # Si el logo de email apunta a un host público (ej. Heroku frontend), usar ese origen.
    logo = email_logo_url.strip()
    if logo.startswith("http") and not _is_local_url(logo):
        base = logo.rsplit("/", 1)[0]
        return f"{base}/{filename}"

    portal = portal_base_url.strip().rstrip("/")
    if portal and not _is_local_url(portal):
        return f"{portal}/{filename}"

    if backend_base:
        return f"{backend_base}{prefix}/branding/{slug if slug != 'logo' else 'logo'}"
    return f"{portal}/{filename}"


def logo_url_for_emails(settings: Settings) -> str:
    return resolve_email_logo_url(
        email_logo_url=settings.email_logo_url,
        backend_public_url=settings.backend_public_url,
        api_prefix=settings.api_prefix,
        portal_base_url=settings.portal_base_url,
    )


def branding_asset_url_for_emails(settings: Settings, slug: str) -> str:
    return resolve_branding_asset_url(
        slug=slug,
        backend_public_url=settings.backend_public_url,
        api_prefix=settings.api_prefix,
        portal_base_url=settings.portal_base_url,
        email_logo_url=settings.email_logo_url,
    )


def store_link_href(url: str) -> str:
    """Href para badges de tienda; vacío = sin destino real por ahora."""
    cleaned = (url or "").strip()
    return cleaned if cleaned else "#"
