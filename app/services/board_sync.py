"""Sincroniza listas del tablero con las columnas Kanban estándar."""

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.constants.default_board_cards import (
    TAXES_CARD_TITLE,
    canonical_default_card_title,
    default_cards_for_column,
    is_taxes_card,
)
from app.constants.kanban_columns import (
    KANBAN_COLUMN_TITLE_ALIASES,
    KANBAN_COLUMN_TITLES,
    canonical_column_title,
    is_funding_sequence_column,
    is_legacy_column_to_remove,
)
from app.models.board import Board, BoardTemplate, BoardTemplateList
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.client import Client
from app.services.default_board_cards import (
    _reorder_board_list_cards_by_defaults,
    merge_missing_default_cards_to_board_list,
    resolve_default_comment_author,
    seed_default_template_cards_for_list,
)
from app.services.storage import get_storage_provider

logger = logging.getLogger(__name__)


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
        if is_funding_sequence_column(title):
            continue
        seed_default_template_cards_for_list(db, template_list=template_list)


def _apply_default_card_title_aliases(lists: list[BoardList]) -> None:
    for board_list in lists:
        for card in board_list.cards:
            renamed = canonical_default_card_title(card.title)
            if renamed != card.title:
                card.title = renamed


def _apply_column_title_aliases(lists: list[BoardList]) -> None:
    for board_list in lists:
        renamed = KANBAN_COLUMN_TITLE_ALIASES.get(board_list.title)
        if renamed:
            board_list.title = renamed


def _load_board_lists(db: Session, board_id: int) -> list[BoardList]:
    return list(
        db.execute(
            select(BoardList)
            .options(selectinload(BoardList.cards))
            .where(BoardList.board_id == board_id)
            .order_by(BoardList.position, BoardList.id)
        )
        .scalars()
        .all()
    )


def _purge_cards(db: Session, cards: list[BoardCard]) -> None:
    card_ids = [card.id for card in cards]
    if not card_ids:
        return

    attachments = list(
        db.execute(select(CardAttachment).where(CardAttachment.card_id.in_(card_ids))).scalars().all()
    )
    if attachments:
        storage = get_storage_provider()
        attachment_ids = [attachment.id for attachment in attachments]
        for attachment in attachments:
            try:
                storage.delete_object(attachment.storage_key)
            except Exception:
                logger.warning(
                    "No se pudo borrar el objeto de storage %s",
                    attachment.storage_key,
                    exc_info=True,
                )
            db.expunge(attachment)
        db.execute(delete(CardAttachment).where(CardAttachment.id.in_(attachment_ids)))

    db.execute(delete(BoardCard).where(BoardCard.id.in_(card_ids)))
    db.flush()


def _purge_board_lists(db: Session, lists: list[BoardList]) -> None:
    list_ids = [item.id for item in lists]
    if not list_ids:
        return
    cards = list(db.execute(select(BoardCard).where(BoardCard.list_id.in_(list_ids))).scalars().all())
    _purge_cards(db, cards)
    db.execute(delete(BoardList).where(BoardList.id.in_(list_ids)))
    db.flush()


def sync_board_lists(db: Session, board: Board) -> None:
    """Normaliza aliases y posiciones. No recrea columnas borradas por el staff."""
    existing_lists = list(board.lists)
    _apply_column_title_aliases(existing_lists)

    for index, board_list in enumerate(sorted(existing_lists, key=lambda item: item.position)):
        board_list.position = index

    db.flush()

    for board_list in existing_lists:
        ordered = sorted(board_list.cards, key=lambda item: item.position)
        for index, card in enumerate(ordered):
            card.position = index


def clear_funding_sequence_cards(db: Session, *, board: Board | None = None) -> int:
    """Deja vacías las columnas de funding. El Funder carga las cards después."""
    list_query = select(BoardList.id, BoardList.title)
    if board is not None:
        list_query = list_query.where(BoardList.board_id == board.id)
    list_ids = [
        row.id
        for row in db.execute(list_query).all()
        if is_funding_sequence_column(row.title)
    ]
    if not list_ids:
        return 0
    result = db.execute(delete(BoardCard).where(BoardCard.list_id.in_(list_ids)))
    deleted = result.rowcount or 0
    if deleted:
        db.flush()
    return deleted


def sync_board_default_cards(db: Session, board: Board) -> None:
    client = db.get(Client, board.client_id)
    for board_list in board.lists:
        if is_funding_sequence_column(board_list.title):
            continue
        merge_missing_default_cards_to_board_list(
            db, board_list=board_list, client=client
        )


def _dedupe_canonical_columns(db: Session, lists: list[BoardList]) -> list[BoardList]:
    keep_by_title: dict[str, BoardList] = {}
    duplicates: list[BoardList] = []
    for board_list in lists:
        title = canonical_column_title(board_list.title)
        if title not in KANBAN_COLUMN_TITLES:
            continue
        kept = keep_by_title.get(title)
        if kept is None:
            keep_by_title[title] = board_list
            continue
        for card in list(board_list.cards):
            card.list_id = kept.id
        duplicates.append(board_list)
    _purge_board_lists(db, duplicates)
    return _load_board_lists(db, lists[0].board_id) if lists else []


def _move_taxes_into_client_todo(db: Session, lists: list[BoardList]) -> None:
    todo = next((item for item in lists if canonical_column_title(item.title) == "Client TO DO"), None)
    if todo is None:
        return

    todo_has_taxes = any(is_taxes_card(card.title) for card in todo.cards)
    extras: list[BoardCard] = []
    for board_list in lists:
        if board_list.id == todo.id:
            continue
        for card in list(board_list.cards):
            if is_taxes_card(card.title):
                extras.append(card)

    for card in extras:
        if todo_has_taxes:
            _purge_cards(db, [card])
        else:
            card.list_id = todo.id
            card.title = TAXES_CARD_TITLE
            todo_has_taxes = True
    db.flush()


def apply_canonical_layout_to_board(db: Session, board: Board) -> None:
    """Aplica el layout actual a un tablero existente. Conserva columnas custom extra."""
    lists = _load_board_lists(db, board.id)
    _apply_column_title_aliases(lists)
    db.flush()

    _purge_board_lists(db, [item for item in lists if is_legacy_column_to_remove(item.title)])
    lists = _load_board_lists(db, board.id)
    if lists:
        lists = _dedupe_canonical_columns(db, lists)

    by_title = {canonical_column_title(item.title): item for item in lists}
    for title in KANBAN_COLUMN_TITLES:
        if title in by_title:
            by_title[title].title = title
            continue
        created = BoardList(board_id=board.id, title=title, position=len(by_title))
        db.add(created)
        db.flush()
        by_title[title] = created
    db.flush()

    lists = _load_board_lists(db, board.id)
    _move_taxes_into_client_todo(db, lists)
    lists = _load_board_lists(db, board.id)
    _apply_default_card_title_aliases(lists)
    db.flush()
    by_title = {canonical_column_title(item.title): item for item in lists}

    for title in KANBAN_COLUMN_TITLES:
        if default_cards_for_column(title):
            continue
        board_list = by_title[title]
        _purge_cards(db, list(board_list.cards))

    credentials = by_title.get("Credenciales")
    if credentials is not None:
        obsolete = [card for card in credentials.cards if card.title == "Datos personales"]
        _purge_cards(db, obsolete)

    client = db.get(Client, board.client_id)
    try:
        comment_author = resolve_default_comment_author(db)
    except Exception:
        comment_author = None
    for title in KANBAN_COLUMN_TITLES:
        board_list = by_title[title]
        if is_funding_sequence_column(title):
            continue
        merge_missing_default_cards_to_board_list(
            db, board_list=board_list, comment_author=comment_author, client=client
        )
        _reorder_board_list_cards_by_defaults(db, board_list)

    lists = _load_board_lists(db, board.id)
    canonical = []
    extras = []
    seen: set[int] = set()
    by_title = {canonical_column_title(item.title): item for item in lists}
    for title in KANBAN_COLUMN_TITLES:
        board_list = by_title[title]
        canonical.append(board_list)
        seen.add(board_list.id)
    for board_list in lists:
        if board_list.id not in seen:
            extras.append(board_list)
    for index, board_list in enumerate([*canonical, *extras]):
        board_list.position = index
    db.flush()
    db.expire(board, ["lists"])


def apply_canonical_layout_to_all_boards(db: Session) -> None:
    template = db.execute(
        select(BoardTemplate)
        .options(joinedload(BoardTemplate.template_lists).joinedload(BoardTemplateList.template_cards))
        .where(BoardTemplate.code == "DEFAULT_ONBOARDING")
    ).unique().scalar_one_or_none()
    if template is not None:
        sync_template_lists(db, template)

    boards = db.execute(select(Board)).scalars().all()
    for board in boards:
        apply_canonical_layout_to_board(db, board)


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
        sync_board_default_cards(db, board)
