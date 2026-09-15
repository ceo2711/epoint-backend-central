from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.client import Client
from app.services.board_sync import sync_board_lists
from app.services.boards import BoardService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Client.__table__,
        Board.__table__,
        BoardList.__table__,
        BoardCard.__table__,
        CardAttachment.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    client = Client(
        first_name="Alexis",
        last_name="Guanique",
        email="alexis@example.com",
        phone="+15551234567",
        status="APROBADO_PARA_ONBOARDING",
        registered_by_user_id=1,
    )
    session.add(client)
    session.flush()
    board = Board(client_id=client.id, template_code="DEFAULT_ONBOARDING")
    session.add(board)
    session.flush()
    todo = BoardList(board_id=board.id, title="Client TO DO", position=0)
    done = BoardList(board_id=board.id, title="Completed", position=1)
    session.add_all([todo, done])
    session.commit()
    session.refresh(board)
    return session, board, todo, done


def test_create_list_appends_custom_column(db_session):
    session, board, _todo, done = db_session
    service = BoardService(session)

    created = service.create_list(board=board, title="  Seguimiento extra  ")

    assert created.title == "Seguimiento extra"
    assert created.position == done.position + 1
    assert session.get(BoardList, created.id) is not None


def test_create_list_rejects_duplicate_title(db_session):
    session, board, _todo, _done = db_session
    service = BoardService(session)

    with pytest.raises(ValueError, match="Ya existe"):
        service.create_list(board=board, title="client to do")


def test_create_list_rejects_reserved_system_title(db_session):
    session, board, _todo, _done = db_session
    service = BoardService(session)

    with pytest.raises(ValueError, match="reservado"):
        service.create_list(board=board, title="Experian")


def test_update_list_renames_custom_column(db_session):
    session, board, _todo, _done = db_session
    service = BoardService(session)
    custom = service.create_list(board=board, title="Seguimiento extra")

    updated = service.update_list(board_list=custom, title="  Seguimiento VIP  ")

    assert updated.title == "Seguimiento VIP"
    assert session.get(BoardList, custom.id).title == "Seguimiento VIP"


def test_update_list_rejects_system_column(db_session):
    session, _board, todo, _done = db_session
    service = BoardService(session)

    with pytest.raises(ValueError, match="estándar"):
        service.update_list(board_list=todo, title="Otro nombre")


def test_delete_list_rejects_system_column(db_session):
    session, _board, todo, _done = db_session
    service = BoardService(session)

    with pytest.raises(ValueError, match="estándar"):
        service.delete_list(board_list=todo)


def test_delete_list_removes_custom_column_and_cards(db_session, monkeypatch):
    session, board, _todo, _done = db_session
    service = BoardService(session)
    custom = service.create_list(board=board, title="Seguimiento extra")
    card = BoardCard(list_id=custom.id, title="Tarea extra", position=0)
    session.add(card)
    session.flush()
    attachment = CardAttachment(
        card_id=card.id,
        type="CLIENT_UPLOAD",
        storage_key="boards/columns/demo.png",
        original_filename="demo.png",
        uploaded_by_user_id=1,
    )
    session.add(attachment)
    session.commit()
    list_id = custom.id
    card_id = card.id
    attachment_id = attachment.id
    deleted_keys: list[str] = []
    monkeypatch.setattr(
        "app.services.boards.get_storage_provider",
        lambda: SimpleNamespace(delete_object=deleted_keys.append),
    )

    service.delete_list(board_list=custom)

    assert session.get(BoardList, list_id) is None
    assert session.get(BoardCard, card_id) is None
    assert session.get(CardAttachment, attachment_id) is None
    assert deleted_keys == ["boards/columns/demo.png"]


def test_sync_board_lists_keeps_custom_columns(db_session):
    session, board, _todo, _done = db_session
    custom = BoardList(board_id=board.id, title="Seguimiento extra", position=99)
    session.add(custom)
    session.commit()
    session.refresh(board)

    sync_board_lists(session, board)
    session.commit()

    titles = {item.title for item in session.execute(select(BoardList).where(BoardList.board_id == board.id)).scalars()}
    assert "Seguimiento extra" in titles
    assert "Client TO DO" in titles
    assert "Completed" in titles
    custom_row = session.get(BoardList, custom.id)
    assert custom_row is not None
    assert custom_row.position >= 12
