"""Recordatorios automáticos a clientes con onboarding incompleto."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import NotificationEventType
from app.services.email.onboarding_reminder import (
    OnboardingReminderEmailPayload,
    send_onboarding_reminder_email,
)
from app.services.notifications import NotificationService
from app.services.onboarding_completeness import (
    analyze_onboarding_gaps,
    fetch_clients_with_active_portal_user,
)
from app.services.whatsapp.onboarding_reminder import (
    OnboardingReminderWhatsAppPayload,
    send_onboarding_reminder_whatsapp,
)

logger = logging.getLogger(__name__)


def _within_onboarding_cooldown(last: datetime | None, cooldown: timedelta, now: datetime) -> bool:
    if last is None:
        return False
    last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return now - last_aware < cooldown


def run_onboarding_reminders(db: Session) -> dict:
    settings = get_settings()
    cooldown = timedelta(hours=max(1, settings.onboarding_reminder_cooldown_hours))
    now = datetime.now(timezone.utc)

    eligible_clients = fetch_clients_with_active_portal_user(db)

    processed = 0
    sent = 0
    skipped = 0
    failed = 0
    portal_login_url = settings.portal_login_url

    for client, portal_user in eligible_clients:
        processed += 1
        gaps = analyze_onboarding_gaps(db, client)
        if not gaps.needs_reminder:
            skipped += 1
            continue
        last = (
            client.last_onboarding_reminder_at
            or getattr(client, "approved_at", None)
            or getattr(client, "created_at", None)
        )
        if _within_onboarding_cooldown(last, cooldown, now):
            skipped += 1
            continue

        pending_items = gaps.all_pending_labels()
        email_ok = send_onboarding_reminder_email(
            OnboardingReminderEmailPayload(
                recipient_email=portal_user.email,
                first_name=client.first_name,
                pending_items=pending_items,
                portal_login_url=portal_login_url,
                client_id=client.id,
            )
        )
        whatsapp_ok = send_onboarding_reminder_whatsapp(
            OnboardingReminderWhatsAppPayload(
                recipient_phone=client.phone,
                first_name=client.first_name,
                pending_items=pending_items,
                portal_login_url=portal_login_url,
                client_id=client.id,
            )
        )

        body_lines = "\n".join(f"• {item}" for item in pending_items)
        NotificationService(db).notify(
            event_type=NotificationEventType.CLIENT_ONBOARDING_INCOMPLETE.value,
            users=[portal_user],
            title="Completa tu onboarding",
            body=(
                f"Hola {client.first_name}, te recordamos ingresar al portal y completar:\n{body_lines}"
            ),
            payload={"client_id": client.id, "pending_items": pending_items},
            channels=["IN_APP"],
            commit=False,
        )

        if email_ok or whatsapp_ok:
            client.last_onboarding_reminder_at = datetime.now(timezone.utc)
            sent += 1
            logger.info(
                "Recordatorio onboarding enviado a cliente #%s (%s) — email=%s whatsapp=%s",
                client.id,
                client.email,
                email_ok,
                whatsapp_ok,
            )
        else:
            failed += 1
            logger.warning(
                "No se pudo enviar recordatorio a cliente #%s (%s)",
                client.id,
                client.email,
            )

    db.commit()
    summary = {
        "processed": processed,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": settings.notifications_dry_run,
    }
    if settings.notifications_dry_run and sent > 0:
        logger.info(
            "Ciclo de recordatorios onboarding (DRY RUN — sin envíos reales): %s",
            {k: v for k, v in summary.items() if k != "dry_run"},
        )
    else:
        logger.info("Ciclo de recordatorios onboarding: %s", summary)
    return summary
