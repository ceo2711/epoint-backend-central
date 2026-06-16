"""Correo de bienvenida al aprobar un cliente (credenciales del portal)."""

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.notifications.templates import client_approved_email_body

logger = logging.getLogger(__name__)

WELCOME_EMAIL_SUBJECT = "¡Bienvenido a ePoint!"


@dataclass(frozen=True, slots=True)
class ClientWelcomeEmailPayload:
    recipient_email: str
    first_name: str
    temp_password: str
    portal_login_url: str
    client_id: int | None = None


def _format_from_address(*, email: str, name: str) -> str:
    if name.strip():
        return f"{name.strip()} <{email.strip()}>"
    return email.strip()


def send_client_welcome_email(payload: ClientWelcomeEmailPayload) -> bool:
    """Envía el email de bienvenida con credenciales del portal vía Resend."""
    settings = get_settings()
    recipient = payload.recipient_email.strip().lower()

    body = client_approved_email_body(
        first_name=payload.first_name,
        email=recipient,
        temp_password=payload.temp_password,
        portal_login_url=payload.portal_login_url,
    )

    if settings.notifications_dry_run:
        logger.info(
            "[DRY RUN] welcome email → %s (cliente_id=%s)\n%s",
            recipient,
            payload.client_id,
            body,
        )
        return True

    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY no configurada — email no enviado a %s", recipient)
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
                "subject": WELCOME_EMAIL_SUBJECT,
                "text": body,
            }
        )
        logger.info(
            "Welcome email enviado a %s (cliente_id=%s, resend_id=%s)",
            recipient,
            payload.client_id,
            response.get("id") if isinstance(response, dict) else response,
        )
        return True
    except Exception:
        logger.exception("Error enviando welcome email a %s", recipient)
        return False
