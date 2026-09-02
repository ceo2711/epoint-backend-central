"""Recordatorios automáticos de saldo de pago pendiente o parcial."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.payment_link import PaymentLink, PaymentLinkStatus
from app.services.email.payment_reminder import PaymentReminderEmailPayload, send_payment_reminder_email
from app.services.payments.amounts import remaining_amount
from app.services.payments.service import PROVIDER_LABELS

logger = logging.getLogger(__name__)

REMINDABLE_STATUSES = (
    PaymentLinkStatus.PENDING.value,
    PaymentLinkStatus.PARTIAL.value,
)


def is_waiting_on_agreed_remainder(link: PaymentLink) -> bool:
    """True si ya hubo un primer pago y falta el saldo acordado.

    El primer cobro pendiente (aunque el link permita parcial) se recuerda
    con el cooldown habitual. El saldo restante espera `remainder_due_on`.
    """
    paid = Decimal(str(link.amount_paid or 0))
    if paid > 0:
        return True
    if getattr(link, "remainder_due_on", None) is not None and not bool(link.allow_partial):
        return True
    return False


def remainder_due_reached(link: PaymentLink, today: date | None = None) -> bool:
    due = getattr(link, "remainder_due_on", None)
    if due is None:
        return False
    return due <= (today or datetime.now(timezone.utc).date())


def fetch_remindable_payment_links(db: Session) -> list[PaymentLink]:
    return list(
        db.execute(
            select(PaymentLink).where(PaymentLink.status.in_(REMINDABLE_STATUSES))
        )
        .scalars()
        .all()
    )


def run_payment_reminders(db: Session) -> dict:
    settings = get_settings()
    cooldown = timedelta(hours=max(1, settings.payment_reminder_cooldown_hours))
    now = datetime.now(timezone.utc)
    today = now.date()

    processed = 0
    sent = 0
    skipped = 0
    failed = 0

    for link in fetch_remindable_payment_links(db):
        processed += 1
        leftover = remaining_amount(link)
        if leftover <= 0 or not link.customer_email:
            skipped += 1
            continue
        if is_waiting_on_agreed_remainder(link) and not remainder_due_reached(link, today):
            skipped += 1
            continue
        last = link.last_payment_reminder_at or link.created_at
        if last is not None:
            last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            if now - last_aware < cooldown:
                skipped += 1
                continue

        ok = send_payment_reminder_email(
            PaymentReminderEmailPayload(
                recipient_email=link.customer_email,
                first_name=link.customer_first_name,
                remaining=leftover,
                total=link.amount,
                paid=link.amount_paid or 0,
                currency=link.currency,
                payment_url=link.payment_url,
                payment_link_id=link.id,
                description=link.description,
                provider_label=PROVIDER_LABELS.get(link.provider, link.provider),
            )
        )
        if ok:
            link.last_payment_reminder_at = now
            sent += 1
            logger.info(
                "Recordatorio de pago enviado a %s (link_id=%s, saldo=%s %s)",
                link.customer_email,
                link.id,
                leftover,
                link.currency,
            )
        else:
            failed += 1
            logger.warning(
                "No se pudo enviar recordatorio de pago a %s (link_id=%s)",
                link.customer_email,
                link.id,
            )

    db.commit()
    summary = {
        "processed": processed,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": settings.notifications_dry_run,
    }
    logger.info("Ciclo de recordatorios de pago: %s", summary)
    return summary
