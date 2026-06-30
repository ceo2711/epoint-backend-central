"""Correo para restablecer contraseña."""

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.notifications.templates import password_reset_email_body

logger = logging.getLogger(__name__)

PASSWORD_RESET_EMAIL_SUBJECT = "Restablecé tu contraseña en ePoint"


@dataclass(frozen=True, slots=True)
class PasswordResetEmailPayload:
    recipient_email: str
    first_name: str
    reset_url: str
    expire_minutes: int


def _format_from_address(*, email: str, name: str) -> str:
    if name.strip():
        return f"{name.strip()} <{email.strip()}>"
    return email.strip()


def send_password_reset_email(payload: PasswordResetEmailPayload) -> bool:
    settings = get_settings()
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    body = password_reset_email_body(
        first_name=payload.first_name,
        reset_url=payload.reset_url,
        expire_minutes=payload.expire_minutes,
    )

    if settings.notifications_dry_run:
        logger.info(
            "[DRY RUN] password reset email → %s\n%s",
            recipient,
            body,
        )
        return True

    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY no configurada — reset email no enviado a %s", recipient)
        return False

    try:
        import resend

        resend.api_key = settings.resend_api_key
        response = resend.Emails.send(
            {
                "from": _format_from_address(
                    email=settings.email_from,
                    name=settings.email_from_name,
                ),
                "to": [recipient],
                "subject": PASSWORD_RESET_EMAIL_SUBJECT,
                "text": body,
            }
        )
        logger.info(
            "Password reset email enviado a %s (resend_id=%s)",
            recipient,
            response.get("id") if isinstance(response, dict) else response,
        )
        return True
    except Exception:
        logger.exception("Error enviando password reset email a %s", recipient)
        return False
