import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings
from app.services.whatsapp.sender import send_whatsapp_from_notification_payload

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
            logger.warning(
                "Email no enviado a %s: configurá SENDGRID_API_KEY en el backend",
                recipient,
            )
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
        return send_whatsapp_from_notification_payload(
            recipient=recipient,
            title=title,
            body=body,
            payload=payload,
        )
