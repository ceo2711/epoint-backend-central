"""Envío de mensajes WhatsApp vía Twilio."""

import json
import logging
from typing import Any

from app.core.config import get_settings
from app.core.phone import format_twilio_whatsapp_from, normalize_whatsapp_number, phones_match

logger = logging.getLogger(__name__)


def send_whatsapp_message(
    *,
    recipient_phone: str,
    title: str,
    body: str,
    content_sid: str | None = None,
    content_variables: dict[str, str] | None = None,
) -> bool:
    """Envía un mensaje WhatsApp usando plantilla Twilio Content o texto plano."""
    settings = get_settings()
    recipient = recipient_phone.strip()

    if settings.notifications_dry_run:
        logger.info(
            "[DRY RUN] WhatsApp → %s: %s — %s (template=%s vars=%s)",
            recipient,
            title,
            body,
            content_sid or "body",
            content_variables,
        )
        return True

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
        from twilio.base.exceptions import TwilioRestException
        from twilio.rest import Client

        phone = normalize_whatsapp_number(recipient, settings.whatsapp_default_country_code)
        from_number = settings.twilio_whatsapp_from
        if not from_number.startswith("whatsapp:"):
            from_number = format_twilio_whatsapp_from(from_number, settings.whatsapp_default_country_code)
        to_number = f"whatsapp:{phone}"

        template_sid = content_sid or settings.twilio_whatsapp_client_approved_content_sid
        logger.info(
            "Enviando WhatsApp: from=%s to=%s template=%s",
            from_number,
            to_number,
            template_sid or "body",
        )

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        if template_sid and content_variables:
            message = client.messages.create(
                from_=from_number,
                to=to_number,
                content_sid=template_sid,
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
        _log_twilio_error(recipient, exc)
        return False
    except Exception:
        logger.exception("Error enviando WhatsApp a %s", recipient)
        return False


def send_whatsapp_from_notification_payload(
    *,
    recipient: str,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Adaptador para NotificationService / otros canales."""
    content_sid = (payload or {}).get("content_sid")
    content_variables = (payload or {}).get("content_variables")
    return send_whatsapp_message(
        recipient_phone=recipient,
        title=title,
        body=body,
        content_sid=str(content_sid) if content_sid else None,
        content_variables=content_variables if isinstance(content_variables, dict) else None,
    )


def _log_twilio_error(recipient: str, exc: Exception) -> None:
    from twilio.base.exceptions import TwilioRestException

    if not isinstance(exc, TwilioRestException):
        logger.error("WhatsApp no enviado a %s: %s", recipient, exc)
        return

    settings = get_settings()
    if exc.code == 63007:
        logger.error(
            "WhatsApp no enviado a %s: TWILIO_WHATSAPP_FROM (%s) no está registrado "
            "como remitente WhatsApp en tu cuenta Twilio. "
            "Usa el Sandbox (whatsapp:+14155238886) para pruebas o registrá el número en "
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
