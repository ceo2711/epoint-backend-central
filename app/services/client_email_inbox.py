"""Hilo de email cliente ↔ staff (saliente e inbound)."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parseaddr

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.models.client import Client
from app.models.enums import NotificationEventType
from app.models.sent_email import (
    EMAIL_DIRECTION_INBOUND,
    EMAIL_DIRECTION_OUTBOUND,
    SentEmail,
)
from app.models.user import User
from app.schemas.common import SentEmailResponse
from app.services.notifications.service import NotificationService

logger = logging.getLogger(__name__)

_QUOTE_SPLIT = re.compile(
    r"\n(?:On .+wrote:|El .+escribió:|-{2,} ?Original Message ?-{2,}|_{2,}\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_email(value: str) -> str:
    _, addr = parseaddr((value or "").strip())
    return (addr or value).strip().lower()


def strip_quoted_reply(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return ""
    match = _QUOTE_SPLIT.search(cleaned)
    if match:
        cleaned = cleaned[: match.start()]
    lines = []
    for line in cleaned.split("\n"):
        if line.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def html_from_plain(text: str) -> str:
    escaped = html.escape(text).replace("\n", "<br />")
    return f"<p>{escaped}</p>" if escaped else "<p></p>"


def serialize_sent_email(row: SentEmail, *, client_name: str = "") -> SentEmailResponse:
    if row.direction == EMAIL_DIRECTION_INBOUND:
        sender = client_name or row.from_email or row.recipient_email
    elif row.sent_by is not None:
        sender = f"{row.sent_by.first_name} {row.sent_by.last_name}".strip()
    else:
        sender = ""
    return SentEmailResponse(
        id=row.id,
        subject=row.subject,
        message_html=row.message_html,
        recipient_email=row.recipient_email,
        sent_by_name=sender,
        created_at=row.created_at,
        direction=row.direction or EMAIL_DIRECTION_OUTBOUND,
        read_at=row.read_at,
        from_email=row.from_email,
    )


def unread_inbound_client_ids(db: Session, client_ids: list[int]) -> set[int]:
    if not client_ids:
        return set()
    rows = db.execute(
        select(SentEmail.client_id)
        .where(
            SentEmail.client_id.in_(client_ids),
            SentEmail.direction == EMAIL_DIRECTION_INBOUND,
            SentEmail.read_at.is_(None),
        )
        .distinct()
    ).all()
    return {int(client_id) for (client_id,) in rows if client_id is not None}


def list_client_thread(db: Session, client: Client) -> list[SentEmailResponse]:
    name = f"{client.first_name} {client.last_name}".strip()
    rows = (
        db.execute(
            select(SentEmail)
            .options(joinedload(SentEmail.sent_by))
            .where(SentEmail.client_id == client.id)
            .order_by(SentEmail.created_at.desc())
        )
        .unique()
        .scalars()
        .all()
    )
    return [serialize_sent_email(row, client_name=name) for row in rows]


def mark_client_inbound_read(db: Session, client_id: int) -> int:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(SentEmail)
        .where(
            SentEmail.client_id == client_id,
            SentEmail.direction == EMAIL_DIRECTION_INBOUND,
            SentEmail.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.commit()
    return int(result.rowcount or 0)


def ingest_inbound_client_email(
    db: Session,
    *,
    from_email: str,
    subject: str,
    text: str,
    html_body: str | None,
    resend_email_id: str | None,
    to_emails: list[str] | None = None,
) -> SentEmail | None:
    sender = normalize_email(from_email)
    if not sender or "@" not in sender:
        logger.info("Inbound email ignorado: From inválido %r", from_email)
        return None

    if resend_email_id:
        existing = db.execute(
            select(SentEmail).where(SentEmail.resend_email_id == resend_email_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    from app.models.client_assignment import ClientAssignment

    client = (
        db.execute(
            select(Client)
            .options(joinedload(Client.assignments).joinedload(ClientAssignment.advisor))
            .where(func.lower(Client.email) == sender)
        )
        .unique()
        .scalar_one_or_none()
    )
    if client is None:
        logger.info("Inbound email sin cliente para %s", sender)
        return None

    body_text = strip_quoted_reply(text) or strip_quoted_reply(
        re.sub(r"<[^>]+>", " ", html_body or "")
    )
    message_html = html_body.strip() if html_body and html_body.strip() else html_from_plain(body_text)
    if not body_text and not html_body:
        body_text = "(sin texto)"
        message_html = html_from_plain(body_text)

    row = SentEmail(
        client_id=client.id,
        recipient_email=(to_emails[0] if to_emails else "") or sender,
        from_email=sender,
        subject=(subject or "(sin asunto)").strip()[:255],
        message_html=message_html,
        direction=EMAIL_DIRECTION_INBOUND,
        resend_email_id=resend_email_id,
        sent_by_user_id=None,
    )
    db.add(row)
    db.flush()

    from app.services.clients import ClientService

    client_service = ClientService(db)
    advisors = client_service._get_active_advisors(client)
    onboarding = client_service._get_mentionable_onboarding(client)
    recipients: list[User] = []
    seen: set[int] = set()
    for user in [*advisors, *onboarding]:
        if user.id in seen or not user.is_active:
            continue
        seen.add(user.id)
        recipients.append(user)

    if recipients:
        preview = body_text.replace("\n", " ").strip()[:140] or "(sin texto)"
        NotificationService(db).notify(
            event_type=NotificationEventType.CLIENT_EMAIL_RECEIVED.value,
            users=recipients,
            title="Nuevo email del cliente",
            body=f"{client.first_name} {client.last_name}: {preview}",
            payload={"client_id": client.id, "email_id": row.id},
            commit=False,
        )

    db.commit()
    db.refresh(row)
    return row
