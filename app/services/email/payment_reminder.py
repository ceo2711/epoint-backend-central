from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.payment_link import _description_block, format_payment_amount
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import payment_reminder_email_body

PAYMENT_REMINDER_SUBJECT = "Recordatorio: completa tu pago en Epoint"


@dataclass(frozen=True, slots=True)
class PaymentReminderEmailPayload:
    recipient_email: str
    first_name: str
    remaining: Decimal
    total: Decimal
    paid: Decimal
    currency: str
    payment_url: str
    payment_link_id: int | None = None
    description: str | None = None
    provider_label: str = "nuestro proveedor de pagos"


def send_payment_reminder_email(payload: PaymentReminderEmailPayload) -> bool:
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    settings = get_settings()
    remaining_formatted = format_payment_amount(amount=payload.remaining, currency=payload.currency)
    total_formatted = format_payment_amount(amount=payload.total, currency=payload.currency)
    paid_formatted = (
        format_payment_amount(amount=payload.paid, currency=payload.currency)
        if payload.paid > 0
        else None
    )
    text_body = payment_reminder_email_body(
        first_name=payload.first_name,
        remaining_formatted=remaining_formatted,
        total_formatted=total_formatted,
        payment_url=payload.payment_url,
        paid_formatted=paid_formatted,
    )
    merchant_line = (
        f"Ya recibimos {paid_formatted}. El saldo pendiente es {remaining_formatted}."
        if paid_formatted
        else f"Todavía tienes un saldo pendiente de {remaining_formatted}."
    )
    html_body = render_html_template(
        "payment_link",
        FIRST_NAME=payload.first_name,
        AMOUNT_FORMATTED=remaining_formatted,
        PAYMENT_URL=payload.payment_url,
        PROVIDER_LABEL=payload.provider_label,
        LOGO_URL=logo_url_for_emails(settings),
        MERCHANT_LINE=merchant_line,
        DESCRIPTION_BLOCK=_description_block(payload.description),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=PAYMENT_REMINDER_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=(
            f"payment reminder id={payload.payment_link_id}"
            if payload.payment_link_id
            else "payment reminder"
        ),
    )
