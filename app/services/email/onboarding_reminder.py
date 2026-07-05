"""Correo recordatorio de onboarding incompleto."""

import logging
from dataclasses import dataclass

from app.services.email.resend_delivery import send_resend_text_email
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


def send_onboarding_reminder_email(payload: OnboardingReminderEmailPayload) -> bool:
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        logger.warning("Email recordatorio omitido: cliente_id=%s sin email", payload.client_id)
        return False

    body = onboarding_reminder_email_body(
        first_name=payload.first_name,
        pending_items=payload.pending_items,
        portal_login_url=payload.portal_login_url,
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=REMINDER_EMAIL_SUBJECT,
        text=body,
        log_context=f"onboarding reminder cliente_id={payload.client_id}" if payload.client_id else "onboarding reminder",
    )
