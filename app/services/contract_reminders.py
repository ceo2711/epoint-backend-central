"""Recordatorios automáticos de contratos enviados y no firmados."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.docusign_envelope import DocusignEnvelope
from app.services.docusign.client import DocusignApiError, DocusignClient
from app.services.email.contract_reminder import ContractReminderEmailPayload, send_contract_reminder_email

logger = logging.getLogger(__name__)

UNSIGNED_ENVELOPE_STATUSES = frozenset({"sent", "delivered"})
MANUAL_ORIGIN = "manual"


def signer_first_name(signer_name: str) -> str:
    parts = (signer_name or "").strip().split()
    return parts[0] if parts else "Hola"


def fetch_unsigned_envelopes(db: Session) -> list[DocusignEnvelope]:
    return list(
        db.execute(
            select(DocusignEnvelope).where(
                DocusignEnvelope.status.in_(UNSIGNED_ENVELOPE_STATUSES),
                DocusignEnvelope.sent_at.isnot(None),
                DocusignEnvelope.origin != MANUAL_ORIGIN,
                or_(
                    DocusignEnvelope.client_id.isnot(None),
                    DocusignEnvelope.prospect_id.isnot(None),
                ),
            )
        )
        .scalars()
        .all()
    )


def fetch_completed_envelopes(db: Session) -> list[DocusignEnvelope]:
    return list(
        db.execute(
            select(DocusignEnvelope).where(DocusignEnvelope.status == "completed")
        )
        .scalars()
        .all()
    )


def _same_email(left: str | None, right: str | None) -> bool:
    return bool(left) and bool(right) and left.strip().lower() == right.strip().lower()


def has_later_completed_signature(
    envelope: DocusignEnvelope,
    completed: list[DocusignEnvelope],
) -> bool:
    """True si el mismo firmante, prospecto o cliente ya firmó un contrato posterior."""
    for row in completed:
        if row.id == envelope.id:
            continue
        if envelope.client_id and row.client_id == envelope.client_id:
            return True
        if envelope.prospect_id and row.prospect_id == envelope.prospect_id:
            return True
        if not _same_email(envelope.signer_email, row.signer_email):
            continue
        if row.id > envelope.id:
            return True
        envelope_sent = envelope.sent_at
        row_sent = row.sent_at
        if envelope_sent and row_sent and row_sent >= envelope_sent:
            return True
    return False


def envelope_is_remindable(
    envelope: DocusignEnvelope,
    completed: list[DocusignEnvelope] | None = None,
) -> bool:
    status = (envelope.status or "").lower()
    if status not in UNSIGNED_ENVELOPE_STATUSES or envelope.sent_at is None:
        return False
    if (getattr(envelope, "origin", None) or "docusign") == MANUAL_ORIGIN:
        return False
    if not envelope.signer_email:
        return False
    if not envelope.client_id and not envelope.prospect_id:
        return False
    client = getattr(envelope, "client", None)
    if client is not None and getattr(client, "docusign_contract_signed_at", None):
        return False
    return not has_later_completed_signature(envelope, completed or [])


def resend_docusign_signing_email(envelope: DocusignEnvelope) -> bool:
    settings = get_settings()
    if not settings.docusign_configured:
        return False
    try:
        client = DocusignClient(
            integration_key=settings.docusign_integration_key,
            impersonated_user_id=settings.docusign_user_id,
            account_id=settings.docusign_account_id,
            private_key_pem=settings.docusign_private_key,
            base_uri=settings.docusign_base_uri,
            auth_server=settings.docusign_auth_server,
        )
        client.resend_envelope(envelope.docusign_envelope_id, signer_email=envelope.signer_email)
        return True
    except DocusignApiError:
        logger.warning(
            "No se pudo reenviar el envelope DocuSign %s",
            envelope.id,
            exc_info=True,
        )
        return False


def send_unsigned_contract_reminder(
    envelope: DocusignEnvelope,
    *,
    resend_docusign: bool = True,
) -> tuple[bool, bool]:
    docusign_resent = resend_docusign_signing_email(envelope) if resend_docusign else False
    email_sent = send_contract_reminder_email(
        ContractReminderEmailPayload(
            recipient_email=envelope.signer_email,
            first_name=signer_first_name(envelope.signer_name),
            contract_subject=envelope.subject,
            envelope_id=envelope.id,
        )
    )
    return email_sent, docusign_resent


def run_contract_reminders(db: Session) -> dict:
    settings = get_settings()
    cooldown = timedelta(hours=max(1, settings.contract_reminder_cooldown_hours))
    now = datetime.now(timezone.utc)

    processed = 0
    sent = 0
    skipped = 0
    failed = 0

    unsigned = fetch_unsigned_envelopes(db)
    completed = fetch_completed_envelopes(db) if unsigned else []

    for envelope in unsigned:
        processed += 1
        if not envelope_is_remindable(envelope, completed):
            skipped += 1
            continue
        last = envelope.last_contract_reminder_at or envelope.sent_at
        if last is None:
            skipped += 1
            continue
        last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if now - last_aware < cooldown:
            skipped += 1
            continue

        email_sent, _docusign_resent = send_unsigned_contract_reminder(envelope)
        if email_sent:
            envelope.last_contract_reminder_at = now
            sent += 1
            logger.info(
                "Recordatorio de contrato enviado a %s (envelope_id=%s)",
                envelope.signer_email,
                envelope.id,
            )
        else:
            failed += 1
            logger.warning(
                "No se pudo enviar recordatorio de contrato a %s (envelope_id=%s)",
                envelope.signer_email,
                envelope.id,
            )

    db.commit()
    summary = {
        "processed": processed,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": settings.notifications_dry_run,
    }
    logger.info("Ciclo de recordatorios de contrato: %s", summary)
    return summary
