"""Correo de bienvenida al aprobar un cliente (credenciales del portal)."""

from dataclasses import dataclass

from app.core.config import get_settings
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import client_approved_email_body

WELCOME_EMAIL_SUBJECT = "¡Bienvenido a ePoint!"


@dataclass(frozen=True, slots=True)
class ClientWelcomeEmailPayload:
    recipient_email: str
    first_name: str
    temp_password: str
    portal_login_url: str
    client_id: int | None = None


def send_client_welcome_email(payload: ClientWelcomeEmailPayload) -> bool:
    """Envía el email de bienvenida con credenciales del portal vía Resend."""
    recipient = payload.recipient_email.strip().lower()
    settings = get_settings()
    text_body = client_approved_email_body(
        first_name=payload.first_name,
        email=recipient,
        temp_password=payload.temp_password,
        portal_login_url=payload.portal_login_url,
    )
    html_body = render_html_template(
        "welcome",
        FIRST_NAME=payload.first_name,
        EMAIL=recipient,
        TEMP_PASSWORD=payload.temp_password,
        PORTAL_LOGIN_URL=payload.portal_login_url,
        LOGO_URL=logo_url_for_emails(settings.frontend_url),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=WELCOME_EMAIL_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=f"welcome cliente_id={payload.client_id}" if payload.client_id else "welcome",
    )
