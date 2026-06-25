"""Recordatorios automáticos a clientes con onboarding incompleto."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.client import Client
from app.models.enums import NotificationEventType
from app.models.role import Role
from app.models.user import User
from app.services.email.onboarding_reminder import (
    OnboardingReminderEmailPayload,
    send_onboarding_reminder_email,
)
from app.services.notifications import NotificationService
from app.services.onboarding_completeness import (
    REMINDER_ELIGIBLE_STATUSES,
    analyze_onboarding_gaps,
)
from app.services.whatsapp.onboarding_reminder import (
    OnboardingReminderWhatsAppPayload,
    send_onboarding_reminder_whatsapp,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def run_onboarding_reminders(db: Session) -> dict:
    settings = get_settings()

    clients = (
        db.execute(
            select(Client)
            .where(
                Client.status.in_(REMINDER_ELIGIBLE_STATUSES),
                Client.approved_at.is_not(None),
            )
            .order_by(Client.id)
        )
        .scalars()
        .all()
    )

    processed = 0
    sent = 0
    skipped = 0
    failed = 0
    portal_login_url = settings.portal_login_url

    for client in clients:
        processed += 1
        gaps = analyze_onboarding_gaps(db, client)
        if not gaps.needs_reminder:
            skipped += 1
            continue

        pending_items = gaps.all_pending_labels()
        email_ok = send_onboarding_reminder_email(
            OnboardingReminderEmailPayload(
                recipient_email=client.email,
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

        portal_user = db.execute(
            select(User)
            .options(joinedload(User.role))
            .join(Role)
            .where(User.client_id == client.id, Role.code == "CLIENT", User.is_active.is_(True))
        ).scalar_one_or_none()

        if portal_user:
            body_lines = "\n".join(f"• {item}" for item in pending_items)
            NotificationService(db).notify(
                event_type=NotificationEventType.CLIENT_ONBOARDING_INCOMPLETE.value,
                users=[portal_user],
                title="Completá tu onboarding",
                body=(
                    f"Hola {client.first_name}, te recordamos ingresar al portal y completar:\n{body_lines}"
                ),
                payload={"client_id": client.id, "pending_items": pending_items},
                channels=["IN_APP"],
                commit=False,
            )

        if email_ok or whatsapp_ok:
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
