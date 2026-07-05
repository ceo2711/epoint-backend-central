"""Correo para restablecer contraseña."""

from dataclasses import dataclass

from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import password_reset_email_body

PASSWORD_RESET_EMAIL_SUBJECT = "Restablecé tu contraseña en ePoint"


@dataclass(frozen=True, slots=True)
class PasswordResetEmailPayload:
    recipient_email: str
    first_name: str
    reset_url: str
    expire_minutes: int


def send_password_reset_email(payload: PasswordResetEmailPayload) -> bool:
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    body = password_reset_email_body(
        first_name=payload.first_name,
        reset_url=payload.reset_url,
        expire_minutes=payload.expire_minutes,
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=PASSWORD_RESET_EMAIL_SUBJECT,
        text=body,
        log_context="password reset",
    )
