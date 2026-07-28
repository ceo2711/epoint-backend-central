from __future__ import annotations

import html
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.payment_link import format_payment_amount
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import client_conversion_welcome_email_body

CLIENT_CONVERSION_WELCOME_EMAIL_SUBJECT = "¡Bienvenido/a a Epoint! Tu perfil está en revisión"


@dataclass(frozen=True, slots=True)
class ClientConversionWelcomeEmailPayload:
    recipient_email: str
    first_name: str
    amount: Decimal
    currency: str
    client_id: int | None = None
    merchant_name: str | None = None


def send_client_conversion_welcome_email(payload: ClientConversionWelcomeEmailPayload) -> bool:
    """Confirma el pago y avisa que Onboarding revisará el nuevo perfil."""
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    settings = get_settings()
    amount_formatted = format_payment_amount(amount=payload.amount, currency=payload.currency)
    merchant_line = (
        f"Tu proceso corresponde a {payload.merchant_name}." if payload.merchant_name else ""
    )
    text_body = client_conversion_welcome_email_body(
        first_name=payload.first_name,
        amount_formatted=amount_formatted,
        merchant_name=payload.merchant_name,
    )
    html_body = render_html_template(
        "client_conversion_welcome",
        FIRST_NAME=html.escape(payload.first_name),
        AMOUNT_FORMATTED=amount_formatted,
        LOGO_URL=logo_url_for_emails(settings),
        MERCHANT_LINE=html.escape(merchant_line),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=CLIENT_CONVERSION_WELCOME_EMAIL_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=(
            f"client conversion welcome id={payload.client_id}"
            if payload.client_id
            else "client conversion welcome"
        ),
    )
