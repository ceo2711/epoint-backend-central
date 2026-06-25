"""Correo recordatorio de onboarding incompleto."""

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.notifications.templates import onboarding_reminder_email_body

logger = logging.getLogger(__name__)

REMINDER_EMAIL_SUBJECT = "Recordatorio: completá tu onboarding en ePoint"


@dataclass(frozen=True, slots=True)
class OnboardingReminderEmailPayload:
    recipient_email: str
    first_name: str
    pending_items: list[str]
    portal_login_url: str
    client_id: int | None = None


def _format_from_address(*, email: str, name: str) -> str:
    if name.strip():
        return f"{name.strip()} <{email.strip()}>"
    return email.strip()


def send_onboarding_reminder_email(payload: OnboardingReminderEmailPayload) -> bool:
    settings = get_settings()
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        logger.warning("Email recordatorio omitido: cliente_id=%s sin email", payload.client_id)
        return False

    body = onboarding_reminder_email_body(
        first_name=payload.first_name,
        pending_items=payload.pending_items,
        portal_login_url=payload.portal_login_url,
    )

    if settings.notifications_dry_run:
        logger.info(
            "[DRY RUN] onboarding reminder email → %s (cliente_id=%s)\n%s",
            recipient,
            payload.client_id,
            body,
        )
        return True

    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY no configurada — recordatorio no enviado a %s", recipient)
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
                "subject": REMINDER_EMAIL_SUBJECT,
                "text": body,
            }
        )
        logger.info(
            "Recordatorio onboarding email enviado a %s (cliente_id=%s, resend_id=%s)",
            recipient,
            payload.client_id,
            response.get("id") if isinstance(response, dict) else response,
        )
        return True
    except Exception:
        logger.exception("Error enviando recordatorio onboarding a %s", recipient)
        return False
