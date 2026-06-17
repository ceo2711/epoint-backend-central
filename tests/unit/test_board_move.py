import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.client import Client
from app.services.boards import BoardService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    client = Client(
        first_name="Alexis",
        last_name="Guanique",
        email="alexis@example.com",
        phone="+15551234567",
        status="APROBADO_PARA_ONBOARDING",
    )
    session.add(client)
    session.flush()
    board = Board(client_id=client.id, template_code="DEFAULT_ONBOARDING")
    session.add(board)
    session.flush()
    left = BoardList(board_id=board.id, title="Client TO DO", position=0)
    right = BoardList(board_id=board.id, title="Completed", position=1)
    session.add_all([left, right])
    session.flush()
    card_a = BoardCard(list_id=left.id, title="Task A", position=0)
    card_b = BoardCard(list_id=left.id, title="Task B", position=1)
    session.add_all([card_a, card_b])
    session.commit()
    return session, card_a, card_b, left, right


def test_move_card_to_another_list(db_session):
    session, card_a, card_b, left, right = db_session
    service = BoardService(session)
    service.move_card(card=card_a, target_list_id=right.id, target_position=0)

    session.refresh(card_a)
    session.refresh(card_b)
    assert card_a.list_id == right.id
    assert card_a.position == 0
    assert card_b.list_id == left.id
    assert card_b.position == 0
