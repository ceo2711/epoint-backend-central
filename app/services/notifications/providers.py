import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings
from app.core.phone import format_twilio_whatsapp_from, normalize_whatsapp_number

logger = logging.getLogger(__name__)


class NotificationChannelProvider(ABC):
    channel: str

    @abstractmethod
    def send(self, recipient: str, title: str, body: str, payload: dict[str, Any] | None = None) -> bool:
        pass


class InAppProvider(NotificationChannelProvider):
    channel = "IN_APP"

    def send(self, recipient: str, title: str, body: str, payload: dict[str, Any] | None = None) -> bool:
        return True


class EmailProvider(NotificationChannelProvider):
    channel = "EMAIL"

    def send(self, recipient: str, title: str, body: str, payload: dict[str, Any] | None = None) -> bool:
        settings = get_settings()
        if not settings.sendgrid_api_key:
            logger.warning("SendGrid no configurado — email no enviado a %s", recipient)
            return False
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            message = Mail(
                from_email=(settings.email_from, settings.email_from_name),
                to_emails=recipient,
                subject=title,
                plain_text_content=body,
            )
            SendGridAPIClient(settings.sendgrid_api_key).send(message)
            return True
        except Exception:
            logger.exception("Error enviando email a %s", recipient)
            return False


class WhatsAppProvider(NotificationChannelProvider):
    channel = "WHATSAPP"

    def send(self, recipient: str, title: str, body: str, payload: dict[str, Any] | None = None) -> bool:
        settings = get_settings()
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            logger.warning("Twilio no configurado — WhatsApp no enviado a %s", recipient)
            return False
        try:
            from twilio.rest import Client

            phone = normalize_whatsapp_number(recipient, settings.whatsapp_default_country_code)
            from_number = settings.twilio_whatsapp_from
            if not from_number.startswith("whatsapp:"):
                from_number = format_twilio_whatsapp_from(from_number, settings.whatsapp_default_country_code)
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(
                from_=from_number,
                to=f"whatsapp:{phone}",
                body=f"*{title}*\n\n{body}",
            )
            return True
        except Exception:
            logger.exception("Error enviando WhatsApp a %s", recipient)
            return False
