"""WhatsApp de bienvenida al aprobar un cliente (credenciales del portal)."""

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.notifications.templates import (
    client_approved_whatsapp_body,
    client_approved_whatsapp_content_variables,
)
from app.services.whatsapp.sender import send_whatsapp_message

logger = logging.getLogger(__name__)

WELCOME_WHATSAPP_TITLE = "¡Bienvenido a ePoint!"


@dataclass(frozen=True, slots=True)
class ClientWelcomeWhatsAppPayload:
    recipient_phone: str
    first_name: str
    email: str
    temp_password: str
    portal_login_url: str
    client_id: int | None = None


def send_client_welcome_whatsapp(payload: ClientWelcomeWhatsAppPayload) -> bool:
    """Envía el WhatsApp de bienvenida con credenciales del portal vía Twilio."""
    settings = get_settings()
    recipient = payload.recipient_phone.strip()
    if not recipient:
        logger.warning(
            "WhatsApp de bienvenida omitido: cliente_id=%s sin teléfono",
            payload.client_id,
        )
        return False

    credential_kwargs = {
        "first_name": payload.first_name,
        "email": payload.email,
        "temp_password": payload.temp_password,
        "portal_login_url": payload.portal_login_url,
    }
    body = client_approved_whatsapp_body(**credential_kwargs)
    content_variables = client_approved_whatsapp_content_variables(**credential_kwargs)
    content_sid = settings.twilio_whatsapp_client_approved_content_sid or None

    return send_whatsapp_message(
        recipient_phone=recipient,
        title=WELCOME_WHATSAPP_TITLE,
        body=body,
        content_sid=content_sid,
        content_variables=content_variables if content_sid else None,
    )
