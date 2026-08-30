import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.client import Client
from app.models.document import Document
from app.services.boards import BoardService


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
    session.flush()
    existing = BoardCard(list_id=todo.id, title="Task A", position=0)
    session.add(existing)
    session.commit()
    return session, todo, done, existing


def test_create_card_at_end(db_session):
    session, todo, _done, existing = db_session
    service = BoardService(session)
    card = service.create_card(board_list=todo, title="New task")

    session.refresh(existing)
    assert card.title == "New task"
    assert card.list_id == todo.id
    assert card.position == 1
    assert existing.position == 0


def test_create_card_at_position(db_session):
    session, todo, _done, existing = db_session
    service = BoardService(session)
    card = service.create_card(board_list=todo, title="Inserted", position=0)

    session.refresh(existing)
    assert card.position == 0
    assert existing.position == 1


def test_delete_card_reorders_remaining(db_session):
    session, todo, _done, existing = db_session
    service = BoardService(session)
    second = service.create_card(board_list=todo, title="Task B")
    third = service.create_card(board_list=todo, title="Task C")

    service.delete_card(card=second)

    session.refresh(existing)
    session.refresh(third)
    remaining = (
        session.execute(
            select(BoardCard)
            .where(BoardCard.list_id == todo.id)
            .order_by(BoardCard.position)
        )
        .scalars()
        .all()
    )
    assert [card.title for card in remaining] == ["Task A", "Task C"]
    assert existing.position == 0
    assert third.position == 1
