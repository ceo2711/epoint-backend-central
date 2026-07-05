"""Correo de bienvenida al aprobar un cliente (credenciales del portal)."""

from dataclasses import dataclass

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
    body = client_approved_email_body(
        first_name=payload.first_name,
        email=recipient,
        temp_password=payload.temp_password,
        portal_login_url=payload.portal_login_url,
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=WELCOME_EMAIL_SUBJECT,
        text=body,
        log_context=f"welcome cliente_id={payload.client_id}" if payload.client_id else "welcome",
    )
