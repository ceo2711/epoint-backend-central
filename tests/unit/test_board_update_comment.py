from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.board import Board
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.card_comment import CardComment
from app.models.client import Client
from app.services.boards import BoardService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Client.__table__,
        Board.__table__,
        BoardList.__table__,
        BoardCard.__table__,
        CardComment.__table__,
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
    session.add(todo)
    session.flush()
    card = BoardCard(list_id=todo.id, title="ChexSystems", position=0)
    session.add(card)
    session.flush()
    comment = CardComment(
        card_id=card.id,
        author_user_id=1,
        body="Paso original",
        is_internal=False,
    )
    session.add(comment)
    session.commit()
    return session, comment


def test_update_comment_changes_body_and_marks_edited(db_session):
    session, comment = db_session
    actor = SimpleNamespace(id=42)
    service = BoardService(session)

    updated = service.update_comment(comment=comment, actor=actor, body="Paso actualizado")

    assert updated.body == "Paso actualizado"
    assert updated.is_internal is False
    assert updated.updated_at is not None


def test_update_comment_can_mark_internal(db_session):
    session, comment = db_session
    actor = SimpleNamespace(id=42)
    service = BoardService(session)

    updated = service.update_comment(
        comment=comment,
        actor=actor,
        body="Solo equipo",
        is_internal=True,
    )

    assert updated.is_internal is True
    assert updated.body == "Solo equipo"


def test_update_comment_rejects_empty_body_without_files(db_session):
    session, comment = db_session
    actor = SimpleNamespace(id=42)
    service = BoardService(session)

    with pytest.raises(ValueError, match="vacío"):
        service.update_comment(comment=comment, actor=actor, body="   ")


def test_update_comment_strips_self_mentions(db_session):
    session, comment = db_session
    actor = SimpleNamespace(id=7)
    service = BoardService(session)

    updated = service.update_comment(
        comment=comment,
        actor=actor,
        body="@[Onboarding](mention:7) revisá esto",
    )

    assert updated.body == "@Onboarding revisá esto"
    assert "(mention:7)" not in updated.body
