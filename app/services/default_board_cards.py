"""Aplica cards por defecto al crear tableros o sincronizar templates."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants.default_board_cards import (
    EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL,
    DefaultBoardCard,
    default_cards_for_column,
)
from app.models.address import Address
from app.models.board import BoardTemplateList
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_comment import CardComment
from app.models.client import Client
from app.models.enums import BoardCardLabel, TaskStatus
from app.models.role import Role
from app.models.user import User

_SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def format_address_line(address: Address) -> str:
    line = f"{address.street} {address.city}, {address.state} {address.zip_code}"
    if address.residence_since_month and address.residence_since_year:
        month_name = _SPANISH_MONTHS[address.residence_since_month - 1]
        line += f" (En {month_name} del {address.residence_since_year})"
    return line


def build_client_personal_data_description(db: Session, client: Client) -> str:
    from app.services.clients import ClientService

    current_addr = db.execute(
        select(Address).where(Address.client_id == client.id, Address.type == "CURRENT")
    ).scalar_one_or_none()

    address_line = format_address_line(current_addr) if current_addr else "—"

    ssn_line = "—"
    if client.ssn_encrypted:
        try:
            ssn_line = ClientService(db).get_client_ssn(client)
        except Exception:
            ssn_line = "—"

    dob_line = client.date_of_birth.strftime("%m/%d/%Y") if client.date_of_birth else "—"

    return f"""**Descripción**

Nombre: {client.full_name}

Email: {client.email}

Phone: {client.phone}

Address: {address_line}

SSN: {ssn_line}

Fecha Nacimiento: {dob_line}"""


def resolve_card_description(
    db: Session,
    *,
    card_def: DefaultBoardCard,
    client: Client | None,
) -> str:
    if card_def.use_client_personal_data and client is not None:
        return build_client_personal_data_description(db, client)
    return card_def.description_md


def refresh_dynamic_card_descriptions(db: Session, *, board_lists: list[BoardList], client: Client) -> None:
    for board_list in board_lists:
        for card in board_list.cards:
            if card.title == "Datos personales":
                card.description_md = build_client_personal_data_description(db, client)
    db.flush()


def resolve_default_comment_author(db: Session) -> User | None:
    author = db.execute(
        select(User).where(User.email == EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL, User.is_active.is_(True))
    ).scalar_one_or_none()
    if author is not None:
        return author

    from app.models.area import Area

    return db.execute(
        select(User)
        .join(Role)
        .join(Area, Area.id == User.area_id)
        .where(
            Role.code == "AREA_LEADER",
            Area.code == "ONBOARDING",
            User.is_active.is_(True),
        )
        .order_by(User.id)
    ).scalar_one_or_none()


def create_board_card_from_default(
    db: Session,
    *,
    board_list: BoardList,
    card_def: DefaultBoardCard,
    comment_author: User | None,
    client: Client | None = None,
) -> BoardCard:
    description = resolve_card_description(db, card_def=card_def, client=client)
    card = BoardCard(
        list_id=board_list.id,
        title=card_def.title,
        description_md=description or None,
        position=card_def.position,
        requires_credentials=card_def.requires_credentials,
        requires_file_upload=card_def.requires_file_upload,
        status=TaskStatus.PENDIENTE.value,
        label=BoardCardLabel.PENDIENTE.value,
    )
    db.add(card)
    db.flush()

    if comment_author is not None:
        for comment_def in card_def.comments:
            db.add(
                CardComment(
                    card_id=card.id,
                    author_user_id=comment_author.id,
                    body=comment_def.body,
                    is_internal=False,
                )
            )
    db.flush()
    return card


def apply_default_cards_to_board_list(
    db: Session,
    *,
    board_list: BoardList,
    comment_author: User | None = None,
    client: Client | None = None,
) -> list[BoardCard]:
    card_defs = default_cards_for_column(board_list.title)
    if not card_defs:
        return []

    author = comment_author if comment_author is not None else resolve_default_comment_author(db)
    created: list[BoardCard] = []
    for card_def in sorted(card_defs, key=lambda item: item.position):
        created.append(
            create_board_card_from_default(
                db,
                board_list=board_list,
                card_def=card_def,
                comment_author=author,
                client=client,
            )
        )
    return created


def _reorder_board_list_cards_by_defaults(db: Session, board_list: BoardList) -> None:
    card_defs = default_cards_for_column(board_list.title)
    if not card_defs:
        return

    position_by_title = {card_def.title: card_def.position for card_def in card_defs}
    cards = list(
        db.execute(select(BoardCard).where(BoardCard.list_id == board_list.id)).scalars().all()
    )

    def sort_key(card: BoardCard) -> tuple[int, int]:
        if card.title in position_by_title:
            return (0, position_by_title[card.title])
        return (1, card.position)

    for index, card in enumerate(sorted(cards, key=sort_key)):
        card.position = index
    db.flush()


def merge_missing_default_cards_to_board_list(
    db: Session,
    *,
    board_list: BoardList,
    comment_author: User | None = None,
    client: Client | None = None,
) -> list[BoardCard]:
    """Inserta tarjetas por defecto que falten (p. ej. template parcial con solo Taxes)."""
    card_defs = default_cards_for_column(board_list.title)
    if not card_defs:
        return []

    existing_titles = {
        title
        for title in db.execute(
            select(BoardCard.title).where(BoardCard.list_id == board_list.id)
        ).scalars().all()
    }

    author = comment_author if comment_author is not None else resolve_default_comment_author(db)
    created: list[BoardCard] = []
    for card_def in sorted(card_defs, key=lambda item: item.position):
        if card_def.title in existing_titles:
            continue
        created.append(
            create_board_card_from_default(
                db,
                board_list=board_list,
                card_def=card_def,
                comment_author=author,
                client=client,
            )
        )

    if created:
        _reorder_board_list_cards_by_defaults(db, board_list)
    return created


def seed_default_template_cards_for_list(
    db: Session,
    *,
    template_list: BoardTemplateList,
) -> None:
    from app.models.board import BoardTemplateCard

    card_defs = default_cards_for_column(template_list.title)
    for card_def in sorted(card_defs, key=lambda item: item.position):
        db.add(
            BoardTemplateCard(
                template_list_id=template_list.id,
                title=card_def.title,
                description_md=card_def.description_md,
                position=card_def.position,
                requires_credentials=card_def.requires_credentials,
                requires_file_upload=card_def.requires_file_upload,
            )
        )
    db.flush()
