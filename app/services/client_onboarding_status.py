"""Transiciones automáticas de estado del cliente durante el onboarding."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants.default_board_cards import is_optional_onboarding_card
from app.constants.kanban_columns import COMPLETED_LIST_TITLE
from app.models.board import Board
from app.models.board_list import BoardList
from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus
from app.services.document_requirements import all_required_documents_approved

logger = logging.getLogger(__name__)


READY_TO_WORK_STATUSES = frozenset(
    {
        ClientStatus.LISTO_PARA_TRABAJAR.value,
        ClientStatus.ONBOARDING_EN_PROGRESO.value,
        ClientStatus.ONBOARDING_COMPLETADO.value,
    }
)

# Si faltan docs mínimos aprobados, el portal vuelve a ocultar el tablero.
DEMOTE_WHEN_DOCS_INCOMPLETE = frozenset(
    {
        ClientStatus.LISTO_PARA_TRABAJAR.value,
        ClientStatus.ONBOARDING_EN_PROGRESO.value,
        ClientStatus.ONBOARDING_COMPLETADO.value,
    }
)


def is_board_unlocked(status: str | None) -> bool:
    """El tablero del portal se habilita recién con datos+docs OK (LISTO_PARA_TRABAJAR+)."""
    return bool(status) and status in READY_TO_WORK_STATUSES


def client_has_board_access(client: Client, documents: list[Document] | None = None) -> bool:
    """Status listo + documentos mínimos realmente aprobados."""
    if not is_board_unlocked(client.status):
        return False
    if documents is None:
        return True
    return all_required_documents_approved(list(documents))


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
    """Avanza o revierte `client.status` según documentos y tablero. No hace commit.

    `board_activity=True` indica que la sincronización fue disparada por una
    acción real sobre el tablero (mover/borrar tarjetas o cambiar su estado);
    solo en ese caso se pasa a ONBOARDING_EN_PROGRESO. Los templates crean
    tarjetas repartidas en varias listas (incluida "Completed"), por lo que la
    distribución inicial del tablero no puede usarse como señal de progreso.
    """
    previous = client.status
    docs = list(db.execute(select(Document).where(Document.client_id == client.id)).scalars().all())
    docs_ok = all_required_documents_approved(docs)

    # Datos completos después de subir docs: salir de EN_CARGA_DATOS aunque no haya
    # un upload nuevo (antes solo avanzaba en confirm_upload).
    if client.status == ClientStatus.EN_CARGA_DATOS.value:
        from app.services.clients import ClientService

        client_service = ClientService(db)
        if client_service.check_data_complete(client):
            if docs_ok:
                try:
                    client_service.promote_to_ready_to_work(client)
                except Exception:
                    logger.exception(
                        "No se pudo promover cliente #%s a LISTO_PARA_TRABAJAR",
                        client.id,
                    )
                    if client.status == ClientStatus.EN_CARGA_DATOS.value:
                        client.status = ClientStatus.LISTO_PARA_TRABAJAR.value
            else:
                client.status = ClientStatus.DOCUMENTOS_EN_REVISION.value
                client_service.on_documents_complete(client=client)
                logger.info(
                    "Cliente #%s pasa a DOCUMENTOS_EN_REVISION: datos completos, docs en revisión",
                    client.id,
                )

    if client.status in DEMOTE_WHEN_DOCS_INCOMPLETE and not docs_ok:
        client.status = ClientStatus.DOCUMENTOS_EN_REVISION.value
        logger.info(
            "Cliente #%s vuelve a DOCUMENTOS_EN_REVISION: faltan documentos mínimos aprobados",
            client.id,
        )
    elif client.status == ClientStatus.DOCUMENTOS_EN_REVISION.value and docs_ok:
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
    required_cards = [card for card in all_cards if not is_optional_onboarding_card(card.title)]
    if not required_cards:
        return client.status != previous

    # No avanzar el tablero si los docs mínimos ya no están OK.
    if not all_required_documents_approved(
        list(db.execute(select(Document).where(Document.client_id == client.id)).scalars().all())
    ):
        return client.status != previous

    all_in_completed = all(card.list_id == completed_list.id for card in required_cards)

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
