"""Allowlist de cuentas de App Store Review.

El 2FA sigue siendo obligatorio para el resto de usuarios. Solo estas
cuentas pueden entrar sin TOTP ni cambio forzado de contraseña.
"""

from __future__ import annotations

from app.core.config import get_settings

DEFAULT_APP_REVIEW_EMAIL = "appreview@epoint.com"


def app_review_emails() -> set[str]:
    raw = get_settings().app_review_emails
    emails = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if not emails:
        emails.add(DEFAULT_APP_REVIEW_EMAIL)
    return emails


def is_app_review_email(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in app_review_emails()
