from __future__ import annotations

import html
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import payment_link_email_body

PAYMENT_LINK_EMAIL_SUBJECT = "Tu link de pago ePoint"


@dataclass(frozen=True, slots=True)
class PaymentLinkEmailPayload:
    recipient_email: str
    first_name: str
    amount: Decimal
    currency: str
    payment_url: str
    provider_label: str
    payment_link_id: int | None = None
    description: str | None = None
    merchant_name: str | None = None


def format_payment_amount(*, amount: Decimal, currency: str) -> str:
    return f"{currency.upper()} {amount:,.2f}"


def _description_block(description: str | None) -> str:
    if not description or not description.strip():
        return ""
    safe = html.escape(description.strip())
    return (
        '<p style="margin:12px 0 0;font-size:14px;color:#555;line-height:1.5;">'
        f"<strong>Concepto:</strong> {safe}"
        "</p>"
    )


def send_payment_link_email(payload: PaymentLinkEmailPayload) -> bool:
    """Envía el link de pago al cliente vía Resend. No lanza excepciones."""
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    settings = get_settings()
    amount_formatted = format_payment_amount(amount=payload.amount, currency=payload.currency)
    merchant_line = (
        f"Tu pago corresponde a {payload.merchant_name}."
        if payload.merchant_name
        else ""
    )
    text_body = payment_link_email_body(
        first_name=payload.first_name,
        amount_formatted=amount_formatted,
        payment_url=payload.payment_url,
        description=payload.description,
        merchant_name=payload.merchant_name,
        provider_label=payload.provider_label,
    )
    html_body = render_html_template(
        "payment_link",
        FIRST_NAME=payload.first_name,
        AMOUNT_FORMATTED=amount_formatted,
        PAYMENT_URL=payload.payment_url,
        PROVIDER_LABEL=payload.provider_label,
        LOGO_URL=logo_url_for_emails(settings.frontend_url),
        MERCHANT_LINE=merchant_line,
        DESCRIPTION_BLOCK=_description_block(payload.description),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=PAYMENT_LINK_EMAIL_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=(
            f"payment link id={payload.payment_link_id}"
            if payload.payment_link_id
            else "payment link"
        ),
    )
