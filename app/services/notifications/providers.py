import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings
from app.core.phone import format_twilio_whatsapp_from, normalize_whatsapp_number, phones_match

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
        settings = get_settings()
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            logger.warning(
                "WhatsApp no enviado a %s: configurá TWILIO_ACCOUNT_SID y TWILIO_AUTH_TOKEN",
                recipient,
            )
            return False
        if not settings.twilio_whatsapp_from:
            logger.warning("WhatsApp no enviado a %s: configurá TWILIO_WHATSAPP_FROM", recipient)
            return False
        if phones_match(recipient, settings.twilio_whatsapp_from, settings.whatsapp_default_country_code):
            logger.warning(
                "WhatsApp no enviado a %s (normalizado %s): coincide con TWILIO_WHATSAPP_FROM",
                recipient,
                normalize_whatsapp_number(recipient, settings.whatsapp_default_country_code),
            )
            return False
        try:
            import json

            from twilio.base.exceptions import TwilioRestException
            from twilio.rest import Client

            phone = normalize_whatsapp_number(recipient, settings.whatsapp_default_country_code)
            from_number = settings.twilio_whatsapp_from
            if not from_number.startswith("whatsapp:"):
                from_number = format_twilio_whatsapp_from(from_number, settings.whatsapp_default_country_code)
            to_number = f"whatsapp:{phone}"

            content_sid = (payload or {}).get("content_sid") or settings.twilio_whatsapp_client_approved_content_sid
            content_variables = (payload or {}).get("content_variables")

            logger.info(
                "Enviando WhatsApp: from=%s to=%s template=%s",
                from_number,
                to_number,
                content_sid or "body",
            )
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            if content_sid and content_variables:
                message = client.messages.create(
                    from_=from_number,
                    to=to_number,
                    content_sid=content_sid,
                    content_variables=json.dumps(content_variables),
                )
            else:
                message = client.messages.create(
                    from_=from_number,
                    to=to_number,
                    body=f"*{title}*\n\n{body}",
                )
            logger.info(
                "WhatsApp aceptado por Twilio: to=%s sid=%s status=%s",
                to_number,
                message.sid,
                message.status,
            )
            return True
        except TwilioRestException as exc:
            if exc.code == 63007:
                logger.error(
                    "WhatsApp no enviado a %s: TWILIO_WHATSAPP_FROM (%s) no está registrado "
                    "como remitente WhatsApp en tu cuenta Twilio. "
                    "Usá el Sandbox (whatsapp:+14155238886) para pruebas o registrá el número en "
                    "Twilio Console → Messaging → WhatsApp senders.",
                    recipient,
                    settings.twilio_whatsapp_from,
                )
            elif exc.code in (63015, 63016, 21608):
                logger.error(
                    "WhatsApp no entregado a %s: el número del cliente no está unido al Sandbox de Twilio. "
                    "Desde ese celular enviá el código join (Twilio Console → WhatsApp Sandbox) al +14155238886. "
                    "Twilio error %s — %s",
                    recipient,
                    exc.code,
                    exc.msg,
                )
            else:
                logger.error(
                    "WhatsApp no enviado a %s: Twilio error %s — %s",
                    recipient,
                    exc.code,
                    exc.msg,
                )
            return False
        except Exception:
            logger.exception("Error enviando WhatsApp a %s", recipient)
            return False
