"""Recordatorios automáticos de tareas pendientes en el tablero del cliente."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants.default_board_cards import is_optional_onboarding_card
from app.constants.kanban_columns import COMPLETED_LIST_TITLE
from app.core.config import get_settings
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.client import Client
from app.models.enums import TaskStatus
from app.services.client_onboarding_status import READY_TO_WORK_STATUSES, client_has_board_access
from app.services.email.board_reminder import BoardReminderEmailPayload, send_board_reminder_email

logger = logging.getLogger(__name__)

CLIENT_PENDING_TASK_STATUSES = frozenset(
    {
        TaskStatus.PENDIENTE.value,
        TaskStatus.EN_PROGRESO.value,
    }
)
MAX_TASKS_IN_EMAIL = 6


def is_completed_list(title: str) -> bool:
    return (title or "").strip().lower() == COMPLETED_LIST_TITLE.lower()


def pending_board_cards(board: Board | None) -> list[BoardCard]:
    if board is None:
        return []
    pending: list[BoardCard] = []
    for board_list in board.lists:
        if is_completed_list(board_list.title):
            continue
        for card in board_list.cards:
            if is_optional_onboarding_card(card.title):
                continue
            status = (card.status or TaskStatus.PENDIENTE.value).upper()
            if status in CLIENT_PENDING_TASK_STATUSES:
                pending.append(card)
    return pending


def pending_task_labels(cards: list[BoardCard], *, limit: int = MAX_TASKS_IN_EMAIL) -> list[str]:
    titles = [card.title.strip() for card in cards if (card.title or "").strip()]
    if len(titles) <= limit:
        return titles
    remaining = len(titles) - limit
    return [*titles[:limit], f"y {remaining} tarea(s) más"]


def fetch_board_unlocked_clients(db: Session) -> list[Client]:
    return list(
        db.execute(
            select(Client)
            .options(
                selectinload(Client.documents),
                selectinload(Client.board).selectinload(Board.lists).selectinload(BoardList.cards),
            )
            .where(Client.status.in_(READY_TO_WORK_STATUSES))
        )
        .unique()
        .scalars()
        .all()
    )


def run_board_reminders(db: Session) -> dict:
    settings = get_settings()
    cooldown = timedelta(hours=max(1, settings.board_reminder_cooldown_hours))
    now = datetime.now(timezone.utc)
    board_url = settings.portal_board_url

    processed = 0
    sent = 0
    skipped = 0
    failed = 0

    for client in fetch_board_unlocked_clients(db):
        processed += 1
        if not client.email:
            skipped += 1
            continue
        if not client_has_board_access(client, list(client.documents or [])):
            skipped += 1
            continue
        cards = pending_board_cards(client.board)
        if not cards:
            skipped += 1
            continue
        last = client.last_board_reminder_at
        if last is not None:
            last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            if now - last_aware < cooldown:
                skipped += 1
                continue

        pending_items = pending_task_labels(cards)
        email_sent = send_board_reminder_email(
            BoardReminderEmailPayload(
                recipient_email=client.email,
                first_name=client.first_name or "Hola",
                pending_items=pending_items,
                board_url=board_url,
                client_id=client.id,
            )
        )
        if email_sent:
            client.last_board_reminder_at = now
            sent += 1
            logger.info(
                "Recordatorio de tablero enviado a %s (client_id=%s, tareas=%s)",
                client.email,
                client.id,
                len(cards),
            )
        else:
            failed += 1
            logger.warning(
                "No se pudo enviar recordatorio de tablero a %s (client_id=%s)",
                client.email,
                client.id,
            )

    db.commit()
    summary = {
        "processed": processed,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "dry_run": settings.notifications_dry_run,
    }
    logger.info("Ciclo de recordatorios de tablero: %s", summary)
    return summary
