"""Email brandeado con mensaje libre del vendedor para prospectos y clientes."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.resend_delivery import send_resend_text_email

# Etiquetas que el editor de texto enriquecido del frontend puede producir.
_ALLOWED_TAGS = {
    "p", "br", "div", "span",
    "strong", "b", "em", "i", "u", "s",
    "a", "ul", "ol", "li", "blockquote",
    "h1", "h2", "h3",
}

_BLOCK_RE = re.compile(r"<(script|style|iframe|object|embed|form)\b[^>]*>.*?</\1>", re.I | re.S)
_EVENT_ATTR_RE = re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JS_URL_RE = re.compile(r"\s(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'>\s]*\2", re.I)
_TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(\s[^>]*)?/?>")


def sanitize_message_html(raw: str) -> str:
    """Permite solo markup básico de texto enriquecido; elimina scripts y handlers."""
    cleaned = _BLOCK_RE.sub("", raw)
    cleaned = _EVENT_ATTR_RE.sub("", cleaned)
    cleaned = _JS_URL_RE.sub("", cleaned)

    def _filter_tag(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1).lower() in _ALLOWED_TAGS else ""

    return _TAG_RE.sub(_filter_tag, cleaned).strip()


def message_html_to_text(message_html: str) -> str:
    """Fallback en texto plano a partir del HTML del mensaje."""
    text = re.sub(r"<\s*(br|/p|/div|/li|/h[1-3])\s*/?>", "\n", message_html, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "- ", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@dataclass(frozen=True, slots=True)
class CustomMessageEmailPayload:
    recipient_email: str
    first_name: str
    subject: str
    message_html: str
    sender_name: str
    log_context: str = "custom message"


def send_custom_message_email(payload: CustomMessageEmailPayload) -> bool:
    """Envía el mensaje del vendedor con la plantilla brandeada. No lanza excepciones."""
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    settings = get_settings()
    safe_message = sanitize_message_html(payload.message_html)
    if not safe_message:
        return False

    subject = payload.subject.strip()
    text_body = (
        f"Hola {payload.first_name},\n\n"
        f"{message_html_to_text(safe_message)}\n\n"
        f"{payload.sender_name}\nEpoint Corporation"
    )
    html_body = render_html_template(
        "custom_message",
        SUBJECT=html_lib.escape(subject),
        FIRST_NAME=html_lib.escape(payload.first_name),
        MESSAGE_HTML=safe_message,
        SENDER_NAME=html_lib.escape(payload.sender_name),
        LOGO_URL=logo_url_for_emails(settings),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=subject,
        text=text_body,
        html=html_body,
        log_context=payload.log_context,
    )
