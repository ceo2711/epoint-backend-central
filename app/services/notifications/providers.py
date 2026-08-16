import json
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


def serialize_expo_push_data(payload: dict[str, Any] | None) -> dict[str, str]:
    """FCM/APNs esperan valores string en `data`; null se omite."""
    if not payload:
        return {}
    data: dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, bool):
            data[str(key)] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            data[str(key)] = json.dumps(value)
        else:
            data[str(key)] = str(value)
    return data


class ExpoPushProvider:
    """Envía notificaciones push vía Expo Push API."""

    ENDPOINT = "https://exp.host/--/api/v2/push/send"
    ANDROID_CHANNEL_ID = "epoint-default"

    def send_to_tokens(
        self,
        tokens: list[str],
        title: str,
        body: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if not tokens:
            return False
        try:
            import httpx

            data = serialize_expo_push_data(payload)
            messages = [
                {
                    "to": token,
                    "title": title,
                    "body": body,
                    "sound": "default",
                    "priority": "high",
                    "channelId": self.ANDROID_CHANNEL_ID,
                    "data": data,
                }
                for token in tokens
            ]
            # Expo acepta hasta ~100 mensajes por request
            ok = True
            with httpx.Client(timeout=15.0) as client:
                for i in range(0, len(messages), 100):
                    chunk = messages[i : i + 100]
                    response = client.post(
                        self.ENDPOINT,
                        json=chunk,
                        headers={
                            "Accept": "application/json",
                            "Accept-Encoding": "gzip, deflate",
                            "Content-Type": "application/json",
                        },
                    )
                    if response.status_code >= 400:
                        logger.warning(
                            "Expo push HTTP %s: %s",
                            response.status_code,
                            response.text[:300],
                        )
                        ok = False
                        continue
                    try:
                        body_json = response.json()
                        tickets = body_json.get("data") if isinstance(body_json, dict) else body_json
                        if isinstance(tickets, list):
                            for ticket in tickets:
                                if isinstance(ticket, dict) and ticket.get("status") == "error":
                                    logger.warning(
                                        "Expo push ticket error: %s — %s",
                                        ticket.get("message"),
                                        ticket.get("details"),
                                    )
                                    ok = False
                    except Exception:
                        logger.debug("No se pudo parsear respuesta Expo push")
            return ok
        except Exception:
            logger.exception("Error enviando push Expo")
            return False
