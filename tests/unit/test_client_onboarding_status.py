"""Tests de transiciones automáticas de estado de onboarding."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus, DocumentType, DocumentVerificationStatus
from app.services.client_onboarding_status import sync_client_onboarding_status


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Client.__table__,
        Board.__table__,
        BoardList.__table__,
        BoardCard.__table__,
        Document.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_client(session, **kwargs) -> Client:
    defaults = {
        "first_name": "Ana",
        "last_name": "García",
        "email": "ana@example.com",
        "phone": "+15551234567",
        "status": ClientStatus.DOCUMENTOS_EN_REVISION.value,
        "registered_by_user_id": 1,
        "approved_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    client = Client(**defaults)
    session.add(client)
    session.flush()
    return client


def _approved_doc(client_id: int, doc_type: str) -> Document:
    return Document(
        client_id=client_id,
        type=doc_type,
        storage_key=f"clients/{client_id}/{doc_type}.pdf",
        original_filename=f"{doc_type}.pdf",
        mime_type="application/pdf",
        verification_status=DocumentVerificationStatus.APROBADO.value,
    )


def _seed_required_docs(db_session, client_id: int) -> None:
    for doc_type in (
        DocumentType.SSN_CARD.value,
        DocumentType.DRIVERS_LICENSE_FRONT.value,
        DocumentType.DRIVERS_LICENSE_BACK.value,
        DocumentType.UTILITY_BILL.value,
    ):
        db_session.add(_approved_doc(client_id, doc_type))


def test_sync_advances_to_listo_para_trabajar_when_docs_approved(db_session):
    client = _make_client(db_session)
    _seed_required_docs(db_session, client.id)
    db_session.commit()

    assert sync_client_onboarding_status(db_session, client) is True
    assert client.status == ClientStatus.LISTO_PARA_TRABAJAR.value


def _make_board(db_session, client_id: int):
    board = Board(client_id=client_id, template_code="DEFAULT_ONBOARDING")
    db_session.add(board)
    db_session.flush()
    todo = BoardList(board_id=board.id, title="Client TO DO", position=0)
    wip = BoardList(board_id=board.id, title="Experian", position=1)
    done = BoardList(board_id=board.id, title="Completed", position=2)
    db_session.add_all([todo, wip, done])
    db_session.flush()
    return board, todo, wip, done


def test_sync_keeps_listo_when_template_cards_untouched(db_session):
    """Regresión: el template crea tarjetas en varias listas; eso no es progreso."""
    client = _make_client(db_session, status=ClientStatus.LISTO_PARA_TRABAJAR.value)
    _seed_required_docs(db_session, client.id)
    _, todo, wip, _ = _make_board(db_session, client.id)
    db_session.add(BoardCard(list_id=todo.id, title="Task A", position=0))
    db_session.add(BoardCard(list_id=wip.id, title="Task B", position=0))
    db_session.commit()
    db_session.refresh(client)

    assert sync_client_onboarding_status(db_session, client) is False
    assert client.status == ClientStatus.LISTO_PARA_TRABAJAR.value


def test_sync_demotes_when_required_doc_rejected(db_session):
    client = _make_client(db_session, status=ClientStatus.LISTO_PARA_TRABAJAR.value)
    _seed_required_docs(db_session, client.id)
    db_session.commit()
    utility = (
        db_session.query(Document)
        .filter_by(client_id=client.id, type=DocumentType.UTILITY_BILL.value)
        .one()
    )
    utility.verification_status = DocumentVerificationStatus.RECHAZADO.value
    db_session.commit()
    db_session.refresh(client)

    assert sync_client_onboarding_status(db_session, client) is True
    assert client.status == ClientStatus.DOCUMENTOS_EN_REVISION.value


def test_sync_advances_to_onboarding_en_progreso_on_board_activity(db_session):
    client = _make_client(db_session, status=ClientStatus.LISTO_PARA_TRABAJAR.value)
    _seed_required_docs(db_session, client.id)
    _, todo, wip, _ = _make_board(db_session, client.id)
    db_session.add(BoardCard(list_id=todo.id, title="Task A", position=0))
    db_session.add(BoardCard(list_id=wip.id, title="Task B", position=0))
    db_session.commit()
    db_session.refresh(client)

    assert sync_client_onboarding_status(db_session, client, board_activity=True) is True
    assert client.status == ClientStatus.ONBOARDING_EN_PROGRESO.value


def test_sync_without_activity_does_not_mark_en_progreso(db_session):
    """Ej.: re-verificación de un documento no debe marcar el tablero como en progreso."""
    client = _make_client(db_session, status=ClientStatus.LISTO_PARA_TRABAJAR.value)
    _seed_required_docs(db_session, client.id)
    _, todo, _, done = _make_board(db_session, client.id)
    db_session.add(BoardCard(list_id=todo.id, title="Task A", position=0))
    db_session.add(BoardCard(list_id=done.id, title="Task B", position=0))
    db_session.commit()
    db_session.refresh(client)

    assert sync_client_onboarding_status(db_session, client) is False
    assert client.status == ClientStatus.LISTO_PARA_TRABAJAR.value


def test_sync_advances_to_completado_when_all_cards_done(db_session):
    client = _make_client(db_session, status=ClientStatus.ONBOARDING_EN_PROGRESO.value)
    _seed_required_docs(db_session, client.id)
    board = Board(client_id=client.id, template_code="DEFAULT_ONBOARDING")
    db_session.add(board)
    db_session.flush()
    todo = BoardList(board_id=board.id, title="Client TO DO", position=0)
    done = BoardList(board_id=board.id, title="Completed", position=1)
    db_session.add_all([todo, done])
    db_session.flush()
    db_session.add(BoardCard(list_id=done.id, title="Done task", position=0))
    db_session.commit()
    db_session.refresh(client)

    assert sync_client_onboarding_status(db_session, client) is True
    assert client.status == ClientStatus.ONBOARDING_COMPLETADO.value
