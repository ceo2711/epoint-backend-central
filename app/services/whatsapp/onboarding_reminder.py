"""WhatsApp recordatorio de onboarding incompleto."""

import logging
from dataclasses import dataclass

from app.services.notifications.templates import onboarding_reminder_whatsapp_body
from app.services.whatsapp.sender import send_whatsapp_message

logger = logging.getLogger(__name__)

REMINDER_WHATSAPP_TITLE = "Recordatorio ePoint"


@dataclass(frozen=True, slots=True)
class OnboardingReminderWhatsAppPayload:
    recipient_phone: str
    first_name: str
    pending_items: list[str]
    portal_login_url: str
    client_id: int | None = None


def send_onboarding_reminder_whatsapp(payload: OnboardingReminderWhatsAppPayload) -> bool:
    recipient = payload.recipient_phone.strip()
    if not recipient:
        logger.warning(
            "WhatsApp recordatorio omitido: cliente_id=%s sin teléfono",
            payload.client_id,
        )
        return False

    body = onboarding_reminder_whatsapp_body(
        first_name=payload.first_name,
        pending_items=payload.pending_items,
        portal_login_url=payload.portal_login_url,
    )

    return send_whatsapp_message(
        recipient_phone=recipient,
        title=REMINDER_WHATSAPP_TITLE,
        body=body,
    )
