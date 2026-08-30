"""Envío de emails vía Resend con soporte para sandbox y redirección en desarrollo."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

RESEND_SANDBOX_HINT = (
    "Resend en modo prueba solo permite enviar a tu email verificado. "
    "Definí EMAIL_DEV_REDIRECT_TO en .env, activá NOTIFICATIONS_DRY_RUN=true "
    "o verificá un dominio en resend.com/domains."
)


def format_from_address(*, email: str, name: str) -> str:
    if name.strip():
        return f"{name.strip()} <{email.strip()}>"
    return email.strip()


def resolve_email_recipient(intended: str, settings: Settings | None = None) -> tuple[str, str, str]:
    """Devuelve (destinatario_efectivo, cuerpo_prefijo, destinatario_original)."""
    settings = settings or get_settings()
    original = intended.strip().lower()
    redirect = settings.email_dev_redirect_to.strip().lower()
    # Evitar valores corruptos del parser de .env (ej. "SENDGRID_API_KEY=").
    if redirect and ("@" not in redirect or "=" in redirect or " " in redirect.split("@", 1)[0]):
        logger.warning(
            "EMAIL_DEV_REDIRECT_TO inválido (%r); se ignora y se envía al destinatario original",
            settings.email_dev_redirect_to.strip()[:80],
        )
        redirect = ""
    if redirect and original != redirect:
        logger.info("Email redirigido de %s → %s (EMAIL_DEV_REDIRECT_TO)", original, redirect)
        prefix = f"[Entorno de prueba — destinatario original: {original}]\n\n"
        return redirect, prefix, original
    return original, "", original


def _is_resend_sandbox_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "testing emails" in message or "verify a domain" in message


def send_resend_text_email(
    *,
    intended_recipient: str,
    subject: str,
    text: str,
    html: str | None = None,
    settings: Settings | None = None,
    log_context: str = "",
) -> bool:
    """Envía email vía Resend (texto plano y HTML opcional). No lanza excepciones."""
    settings = settings or get_settings()
    recipient, body_prefix, original = resolve_email_recipient(intended_recipient, settings)

    if settings.notifications_dry_run:
        logger.info(
            "[DRY RUN] email → %s%s\n%s",
            recipient,
            f" ({log_context})" if log_context else "",
            body_prefix + text,
        )
        return True

    if not settings.resend_api_key:
        logger.warning(
            "RESEND_API_KEY no configurada — email no enviado a %s%s",
            original,
            f" ({log_context})" if log_context else "",
        )
        return False

    try:
        import resend

        resend.api_key = settings.resend_api_key
        payload: dict[str, Any] = {
            "from": format_from_address(
                email=settings.email_from,
                name=settings.email_from_name,
            ),
            "to": [recipient],
            "subject": subject,
            "text": body_prefix + text,
        }
        if html:
            payload["html"] = body_prefix + html
        reply_to = settings.email_reply_to.strip()
        if reply_to:
            payload["reply_to"] = reply_to
        else:
            logger.warning(
                "EMAIL_REPLY_TO vacío: la respuesta del cliente irá a %s "
                "(dominio de envío, sin MX). El hilo inbound no va a recibirla.",
                settings.email_from,
            )

        response: Any = resend.Emails.send(payload)
        logger.info(
            "Email enviado a %s (destino original=%s%s, resend_id=%s)",
            recipient,
            original,
            f", {log_context}" if log_context else "",
            response.get("id") if isinstance(response, dict) else response,
        )
        return True
    except Exception as exc:
        if _is_resend_sandbox_error(exc):
            logger.warning(
                "Email no enviado a %s (sandbox Resend): %s. %s",
                original,
                exc,
                RESEND_SANDBOX_HINT,
            )
            return False
        logger.exception(
            "Error enviando email a %s%s",
            original,
            f" ({log_context})" if log_context else "",
        )
        return False
