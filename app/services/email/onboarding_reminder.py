"""Correo recordatorio de onboarding incompleto."""

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.email.html_templates import (
    logo_url_for_emails,
    pending_items_html,
    render_html_template,
)
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import onboarding_reminder_email_body

logger = logging.getLogger(__name__)

REMINDER_EMAIL_SUBJECT = "Recordatorio: completá tu onboarding en ePoint"
REMINDER_EMAIL_SUBJECT_EN = "Reminder: complete your ePoint onboarding"


@dataclass(frozen=True, slots=True)
class OnboardingReminderEmailPayload:
    recipient_email: str
    first_name: str
    pending_items: list[str]
    portal_login_url: str
    client_id: int | None = None
    locale: str = "es"


def send_onboarding_reminder_email(payload: OnboardingReminderEmailPayload) -> bool:
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        logger.warning("Email recordatorio omitido: cliente_id=%s sin email", payload.client_id)
        return False

    locale = payload.locale.lower()
    is_en = locale.startswith("en")
    settings = get_settings()
    items_html = pending_items_html(payload.pending_items)

    text_body = onboarding_reminder_email_body(
        first_name=payload.first_name,
        pending_items=payload.pending_items,
        portal_login_url=payload.portal_login_url,
        locale=locale,
    )
    html_body = render_html_template(
        "onboarding_reminder_en" if is_en else "onboarding_reminder",
        FIRST_NAME=payload.first_name,
        PENDING_ITEMS_HTML=items_html,
        PORTAL_LOGIN_URL=payload.portal_login_url,
        LOGO_URL=logo_url_for_emails(settings.frontend_url),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=REMINDER_EMAIL_SUBJECT_EN if is_en else REMINDER_EMAIL_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=f"onboarding reminder cliente_id={payload.client_id}" if payload.client_id else "onboarding reminder",
    )
