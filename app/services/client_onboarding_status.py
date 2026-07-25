"""Transiciones automáticas de estado del cliente durante el onboarding."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants.kanban_columns import KANBAN_COLUMN_TITLES
from app.models.board import Board
from app.models.board_list import BoardList
from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus
from app.services.document_requirements import all_required_documents_approved

logger = logging.getLogger(__name__)

COMPLETED_LIST_TITLE = KANBAN_COLUMN_TITLES[-1]

READY_TO_WORK_STATUSES = frozenset(
    {
        ClientStatus.LISTO_PARA_TRABAJAR.value,
        ClientStatus.ONBOARDING_EN_PROGRESO.value,
        ClientStatus.ONBOARDING_COMPLETADO.value,
    }
)


def _load_client_board(db: Session, client_id: int) -> Board | None:
    return (
        db.execute(
            select(Board)
            .options(selectinload(Board.lists).selectinload(BoardList.cards))
            .where(Board.client_id == client_id)
        )
        .unique()
        .scalar_one_or_none()
    )


def sync_client_onboarding_status(
    db: Session,
    client: Client,
    *,
    board_activity: bool = False,
) -> bool:
    """Avanza `client.status` según documentos y tablero. No hace commit.

    `board_activity=True` indica que la sincronización fue disparada por una
    acción real sobre el tablero (mover/borrar tarjetas o cambiar su estado);
    solo en ese caso se pasa a ONBOARDING_EN_PROGRESO. Los templates crean
    tarjetas repartidas en varias listas (incluida "Completed"), por lo que la
    distribución inicial del tablero no puede usarse como señal de progreso.
    """
    previous = client.status

    if client.status == ClientStatus.DOCUMENTOS_EN_REVISION.value:
        docs = db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
        if all_required_documents_approved(list(docs)):
            from app.services.clients import ClientService

            try:
                ClientService(db).promote_to_ready_to_work(client)
            except Exception:
                logger.exception(
                    "No se pudo promover cliente #%s a LISTO_PARA_TRABAJAR",
                    client.id,
                )
                if client.status == ClientStatus.DOCUMENTOS_EN_REVISION.value:
                    client.status = ClientStatus.LISTO_PARA_TRABAJAR.value

    board = _load_client_board(db, client.id)
    if board is None:
        return client.status != previous

    lists = sorted(board.lists, key=lambda row: row.position)
    if not lists:
        return client.status != previous

    completed_list = next(
        (row for row in lists if row.title == COMPLETED_LIST_TITLE),
        lists[-1],
    )
    all_cards = [card for board_list in lists for card in board_list.cards]
    if not all_cards:
        return client.status != previous

    all_in_completed = all(card.list_id == completed_list.id for card in all_cards)

    if all_in_completed and client.status in {
        ClientStatus.LISTO_PARA_TRABAJAR.value,
        ClientStatus.ONBOARDING_EN_PROGRESO.value,
    }:
        client.status = ClientStatus.ONBOARDING_COMPLETADO.value
    elif board_activity and not all_in_completed and client.status in {
        ClientStatus.LISTO_PARA_TRABAJAR.value,
        ClientStatus.DOCUMENTOS_EN_REVISION.value,
    }:
        client.status = ClientStatus.ONBOARDING_EN_PROGRESO.value

    if client.status != previous:
        logger.info(
            "Estado onboarding cliente #%s actualizado: %s → %s",
            client.id,
            previous,
            client.status,
        )
    return client.status != previous
