from __future__ import annotations

import html
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.email.html_templates import (
    logo_url_for_emails,
    pending_items_html,
    render_html_template,
)
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import board_reminder_email_body

BOARD_REMINDER_SUBJECT = "Recordatorio: tenés tareas pendientes en tu tablero de Epoint"


@dataclass(frozen=True, slots=True)
class BoardReminderEmailPayload:
    recipient_email: str
    first_name: str
    pending_items: list[str]
    board_url: str
    client_id: int | None = None


def send_board_reminder_email(payload: BoardReminderEmailPayload) -> bool:
    recipient = payload.recipient_email.strip().lower()
    if not recipient:
        return False

    settings = get_settings()
    text_body = board_reminder_email_body(
        first_name=payload.first_name,
        pending_items=payload.pending_items,
        board_url=payload.board_url,
    )
    html_body = render_html_template(
        "board_reminder",
        FIRST_NAME=html.escape(payload.first_name),
        PENDING_ITEMS_HTML=pending_items_html(payload.pending_items),
        BOARD_URL=payload.board_url,
        LOGO_URL=logo_url_for_emails(settings),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=BOARD_REMINDER_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=(
            f"board reminder cliente_id={payload.client_id}"
            if payload.client_id
            else "board reminder"
        ),
    )
