"""TOTP (Microsoft Authenticator / Google Authenticator compatible)."""

from __future__ import annotations

import pyotp

from app.core.config import get_settings
from app.core.encryption import decrypt_value, encrypt_value

TOTP_ISSUER = "ePoint CRM"


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_provisioning_uri(*, email: str, secret: str) -> str:
    settings = get_settings()
    issuer = settings.app_name if settings.app_name else TOTP_ISSUER
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def encrypt_totp_secret(secret: str) -> str:
    return encrypt_value(secret)


def decrypt_totp_secret(encrypted: str) -> str:
    return decrypt_value(encrypted)


def verify_totp_code(*, secret: str, code: str) -> bool:
    normalized = code.strip().replace(" ", "")
    if not normalized.isdigit() or len(normalized) != 6:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(normalized, valid_window=1)
