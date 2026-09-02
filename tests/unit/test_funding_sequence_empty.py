from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.client import Client
from app.services.board_sync import clear_funding_sequence_cards


def test_clear_funding_sequence_cards_leaves_other_columns():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Client.__table__, Board.__table__, BoardList.__table__, BoardCard.__table__])
    session = sessionmaker(bind=engine)()
    client = Client(
        first_name="Ana",
        last_name="Test",
        email="ana@example.com",
        phone="+15550001111",
        status="APROBADO_PARA_ONBOARDING",
        registered_by_user_id=1,
    )
    session.add(client)
    session.flush()
    board = Board(client_id=client.id, template_code="DEFAULT_ONBOARDING")
    session.add(board)
    session.flush()
    todo = BoardList(board_id=board.id, title="Client TO DO", position=0)
    funding = BoardList(board_id=board.id, title="Personal Funding Sequence (2)", position=1)
    session.add_all([todo, funding])
    session.flush()
    session.add_all(
        [
            BoardCard(list_id=todo.id, title="Reportes", position=0),
            BoardCard(list_id=funding.id, title="JP Morgan Chase", position=0),
            BoardCard(list_id=funding.id, title="Sofi Bank", position=1),
        ]
    )
    session.commit()

    deleted = clear_funding_sequence_cards(session, board=board)
    session.commit()

    assert deleted == 2
    remaining = session.execute(select(BoardCard)).scalars().all()
    assert [card.title for card in remaining] == ["Reportes"]
