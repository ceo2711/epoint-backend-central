from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.constants.kanban_columns import KANBAN_COLUMN_TITLES
from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.client import Client
from app.services.board_sync import apply_canonical_layout_to_board


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Client.__table__,
            Board.__table__,
            BoardList.__table__,
            BoardCard.__table__,
            CardAttachment.__table__,
        ],
    )
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
    return session, board


def test_apply_canonical_layout_rebuilds_legacy_board():
    session, board = _session()
    todo = BoardList(board_id=board.id, title="Client TO DO", position=0)
    credits = BoardList(board_id=board.id, title="Pendientes EpointCredits", position=1)
    ideas = BoardList(board_id=board.id, title="Ideas a realizar", position=2)
    creds = BoardList(board_id=board.id, title="Credenciales", position=3)
    experian = BoardList(board_id=board.id, title="Experian", position=4)
    banks = BoardList(board_id=board.id, title="Cuentas de banco", position=5)
    personal_2 = BoardList(board_id=board.id, title="Personal Funding Sequence (2)", position=6)
    done = BoardList(board_id=board.id, title="Completed", position=7)
    custom = BoardList(board_id=board.id, title="Seguimiento extra", position=8)
    session.add_all([todo, credits, ideas, creds, experian, banks, personal_2, done, custom])
    session.flush()
    session.add_all(
        [
            BoardCard(list_id=todo.id, title="Reportes: Experian, Equifax y TransUnion", position=0),
            BoardCard(list_id=ideas.id, title="Informe de Taxes", position=0),
            BoardCard(list_id=creds.id, title="Datos personales", position=0),
            BoardCard(list_id=creds.id, title="Experian", position=1),
            BoardCard(list_id=experian.id, title="Accounts", position=0),
            BoardCard(list_id=experian.id, title="Inquiries", position=1),
            BoardCard(list_id=credits.id, title="Tarea epoint", position=0),
            BoardCard(list_id=done.id, title="Inquiries", position=0),
            BoardCard(list_id=custom.id, title="Nota custom", position=0),
        ]
    )
    session.commit()

    apply_canonical_layout_to_board(session, board)
    session.commit()

    rows = list(
        session.execute(
            select(BoardList).where(BoardList.board_id == board.id).order_by(BoardList.position)
        ).scalars()
    )
    titles = [row.title for row in rows]
    assert titles[:8] == list(KANBAN_COLUMN_TITLES)
    assert titles[-1] == "Seguimiento extra"
    assert "Completed" not in titles
    assert "Pendientes EpointCredits" not in titles
    assert "Cuentas de banco" not in titles
    assert "Personal Funding Sequence (2)" not in titles

    todo_cards = [
        card.title
        for card in session.execute(select(BoardCard).where(BoardCard.list_id == rows[0].id).order_by(BoardCard.position))
        .scalars()
        .all()
    ]
    assert todo_cards[:4] == [
        "Reportes: Experian, Equifax y TransUnion",
        "Apertura de Cuentas (Buros Secundarios)",
        "Lista de bancos con relación",
        "Informe de Taxes",
    ]

    cred_cards = [
        card.title
        for card in session.execute(select(BoardCard).where(BoardCard.list_id == rows[1].id).order_by(BoardCard.position))
        .scalars()
        .all()
    ]
    assert cred_cards == [
        "Experian",
        "Equifax",
        "TransUnion",
        "ChexSystems",
        "Innovis",
        "Experian Clarity Services",
    ]

    empty_titles = {
        "Ideas a realizar",
        "Experian",
        "Equifax",
        "Transunion",
        "Personal Funding Sequence",
        "Business Funding Sequence",
    }
    for row in rows:
        if row.title in empty_titles:
            count = session.execute(select(BoardCard).where(BoardCard.list_id == row.id)).scalars().all()
            assert count == []

    custom_cards = session.execute(select(BoardCard).where(BoardCard.list_id == rows[-1].id)).scalars().all()
    assert [card.title for card in custom_cards] == ["Nota custom"]


def test_apply_canonical_layout_creates_missing_columns_on_empty_board():
    session, board = _session()
    session.commit()

    apply_canonical_layout_to_board(session, board)
    session.commit()

    rows = list(
        session.execute(
            select(BoardList).where(BoardList.board_id == board.id).order_by(BoardList.position)
        ).scalars()
    )
    assert [row.title for row in rows] == list(KANBAN_COLUMN_TITLES)
