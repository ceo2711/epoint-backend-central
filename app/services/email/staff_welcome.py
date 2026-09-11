"""Correo de bienvenida al crear un empleado (credenciales de la plataforma)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.models.user import User
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import staff_welcome_email_body

logger = logging.getLogger(__name__)

STAFF_WELCOME_EMAIL_SUBJECT = "Tu cuenta de Epoint está lista"


@dataclass(frozen=True, slots=True)
class StaffWelcomeEmailPayload:
    recipient_email: str
    first_name: str
    temp_password: str
    login_url: str
    role_line: str = ""
    user_id: int | None = None


def staff_role_line(user: User) -> str:
    parts: list[str] = []
    if user.role is not None and user.role.name:
        parts.append(user.role.name)
    if user.area is not None and user.area.name:
        parts.append(user.area.name)
    if user.sede is not None and user.sede.name:
        parts.append(user.sede.name)
    if not parts:
        return ""
    return f"Tu perfil: {' · '.join(parts)}."


def send_staff_welcome_email(payload: StaffWelcomeEmailPayload) -> bool:
    """Envía el email de bienvenida con credenciales de empleado vía Resend."""
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False
    settings = get_settings()
    text_body = staff_welcome_email_body(
        first_name=payload.first_name,
        email=recipient,
        temp_password=payload.temp_password,
        login_url=payload.login_url,
        role_line=payload.role_line,
    )
    html_body = render_html_template(
        "staff_welcome",
        FIRST_NAME=payload.first_name,
        EMAIL=recipient,
        TEMP_PASSWORD=payload.temp_password,
        LOGIN_URL=payload.login_url,
        ROLE_LINE=payload.role_line,
        LOGO_URL=logo_url_for_emails(settings),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=STAFF_WELCOME_EMAIL_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=f"staff welcome user_id={payload.user_id}" if payload.user_id else "staff welcome",
    )


def notify_staff_account_created(user: User, password: str) -> bool:
    """Envía la bienvenida tras crear un empleado. No lanza: el alta no debe fallar."""
    settings = get_settings()
    try:
        sent = send_staff_welcome_email(
            StaffWelcomeEmailPayload(
                recipient_email=user.email,
                first_name=user.first_name,
                temp_password=password,
                login_url=settings.portal_login_url,
                role_line=staff_role_line(user),
                user_id=user.id,
            )
        )
    except Exception:
        logger.exception("No se pudo enviar bienvenida de empleado a %s (user_id=%s)", user.email, user.id)
        return False
    if not sent:
        logger.warning("Bienvenida de empleado no enviada a %s (user_id=%s)", user.email, user.id)
    return sent
