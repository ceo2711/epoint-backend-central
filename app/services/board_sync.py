"""Sincroniza listas del tablero con las columnas Kanban estándar."""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.constants.kanban_columns import KANBAN_COLUMN_TITLES
from app.models.board import Board, BoardTemplate, BoardTemplateCard, BoardTemplateList
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.services.default_board_cards import seed_default_template_cards_for_list


def sync_template_lists(db: Session, template: BoardTemplate) -> None:
    for t_list in list(template.template_lists):
        for t_card in list(t_list.template_cards):
            db.delete(t_card)
        db.delete(t_list)
    db.flush()

    for position, title in enumerate(KANBAN_COLUMN_TITLES):
        template_list = BoardTemplateList(template_id=template.id, title=title, position=position)
        db.add(template_list)
        db.flush()
        seed_default_template_cards_for_list(db, template_list=template_list)


def sync_board_lists(db: Session, board: Board) -> None:
    existing_lists = list(board.lists)
    cards: list[BoardCard] = []
    for board_list in existing_lists:
        cards.extend(list(board_list.cards))

    target_titles = set(KANBAN_COLUMN_TITLES)
    title_to_list: dict[str, BoardList] = {}

    for position, title in enumerate(KANBAN_COLUMN_TITLES):
        match = next((item for item in existing_lists if item.title == title), None)
        if match is None:
            match = BoardList(board_id=board.id, title=title, position=position)
            db.add(match)
            db.flush()
        else:
            match.position = position
        title_to_list[title] = match

    default_list = title_to_list[KANBAN_COLUMN_TITLES[0]]
    valid_ids = {item.id for item in title_to_list.values()}

    for card in cards:
        if card.list_id not in valid_ids:
            card.list_id = default_list.id

    for board_list in existing_lists:
        if board_list.title not in target_titles:
            db.delete(board_list)

    db.flush()

    for board_list in title_to_list.values():
        ordered = sorted(board_list.cards, key=lambda item: item.position)
        for index, card in enumerate(ordered):
            card.position = index


def sync_all_boards(db: Session) -> None:
    template = db.execute(
        select(BoardTemplate)
        .options(joinedload(BoardTemplate.template_lists).joinedload(BoardTemplateList.template_cards))
        .where(BoardTemplate.code == "DEFAULT_ONBOARDING")
    ).unique().scalar_one_or_none()
    if template is not None:
        sync_template_lists(db, template)

    boards = db.execute(
        select(Board).options(joinedload(Board.lists).joinedload(BoardList.cards))
    ).unique().scalars().all()
    for board in boards:
        sync_board_lists(db, board)
