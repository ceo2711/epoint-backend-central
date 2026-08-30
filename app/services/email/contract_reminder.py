from __future__ import annotations

import html
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.email.html_templates import logo_url_for_emails, render_html_template
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import contract_reminder_email_body

CONTRACT_REMINDER_SUBJECT = "Recordatorio: firmá tu contrato en Epoint"


@dataclass(frozen=True, slots=True)
class ContractReminderEmailPayload:
    recipient_email: str
    first_name: str
    contract_subject: str
    envelope_id: int | None = None


def send_contract_reminder_email(payload: ContractReminderEmailPayload) -> bool:
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    settings = get_settings()
    subject = payload.contract_subject.strip() or "Contrato Epoint"
    text_body = contract_reminder_email_body(
        first_name=payload.first_name,
        contract_subject=subject,
    )
    html_body = render_html_template(
        "contract_reminder",
        FIRST_NAME=payload.first_name,
        CONTRACT_SUBJECT=html.escape(subject),
        LOGO_URL=logo_url_for_emails(settings),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=CONTRACT_REMINDER_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=(
            f"contract reminder envelope_id={payload.envelope_id}"
            if payload.envelope_id
            else "contract reminder"
        ),
    )
