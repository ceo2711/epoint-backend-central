from unittest.mock import MagicMock, patch

from app.constants.default_board_cards import (
    EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL,
    TAXES_CARD_COLUMN,
    TAXES_CARD_TITLE,
    default_cards_for_column,
    is_optional_onboarding_card,
)
from app.services.default_board_cards import (
    apply_default_cards_to_board_list,
    build_client_personal_data_description,
    create_board_card_from_default,
    merge_missing_default_cards_to_board_list,
    resolve_default_comment_author,
)


def test_client_todo_default_cards():
    cards = default_cards_for_column("Client TO DO")

    assert len(cards) == 3
    assert cards[0].title == "Reportes: Experian, Equifax y TransUnion"
    assert cards[1].title == "Apertura de Cuentas & Freeze"
    assert cards[2].title == "Lista de bancos con relacion"
    assert cards[0].requires_file_upload is True
    assert cards[1].requires_credentials is True
    assert len(cards[1].comments) == 3
    assert "experian.com" in cards[0].description_md
    assert "1-800-456-1244" in cards[1].description_md
    assert TAXES_CARD_TITLE not in {card.title for card in cards}


def test_taxes_card_lives_in_ideas_and_is_optional():
    cards = default_cards_for_column(TAXES_CARD_COLUMN)

    assert len(cards) == 1
    assert cards[0].title == TAXES_CARD_TITLE
    assert cards[0].requires_file_upload is True
    assert "no es obligatoria" in cards[0].description_md
    assert "entidad financiera" in cards[0].description_md
    assert is_optional_onboarding_card(TAXES_CARD_TITLE) is True
    assert is_optional_onboarding_card("Apertura de Cuentas & Freeze") is False


def test_credenciales_default_cards():
    cards = default_cards_for_column("Credenciales")

    assert len(cards) == 7
    assert cards[0].title == "Datos personales"
    assert cards[0].use_client_personal_data is True
    assert [card.title for card in cards[1:]] == [
        "Experian",
        "Equifax",
        "TransUnion",
        "ChexSystems",
        "Innovis",
        "Clarity Services",
    ]
    assert cards[-1].requires_file_upload is True
    assert cards[1].requires_credentials is True
    assert cards[2].requires_credentials is True
    assert cards[3].requires_credentials is True
    assert cards[-1].description_md == ""


def test_experian_default_cards():
    cards = default_cards_for_column("Experian")

    assert len(cards) == 2
    assert cards[0].title == "Accounts"
    assert cards[1].title == "Inquiries"
    assert "Balance:" in cards[0].description_md
    assert "CAPITAL ONE" not in cards[0].description_md


def test_transunion_default_cards():
    cards = default_cards_for_column("Transunion")

    assert len(cards) == 2
    assert cards[0].title == "Accounts"
    assert cards[1].title == "Inquiries"
    assert cards[0].description_md == default_cards_for_column("Experian")[0].description_md
    assert "**Envíos**" not in cards[0].description_md


def test_equifax_default_cards():
    cards = default_cards_for_column("Equifax")

    assert len(cards) == 2
    assert cards[0].title == "Accounts"
    assert cards[1].title == "Inquiries"
    assert cards[0].description_md == default_cards_for_column("Experian")[0].description_md
    assert "**Envíos**" not in cards[0].description_md


def test_personal_funding_sequence_2_default_cards():
    cards = default_cards_for_column("Personal Fonding Sequence (2)")

    assert len(cards) == 13
    assert [card.title for card in cards] == [
        "JP Morgan Chase",
        "Sofi Bank",
        "Navy Federal Credit Union",
        "Lightstream By Truist",
        "CAPITAL ONE",
        "DISCOVER CARD",
        "Citi Bank",
        "Upgrade",
        "Citizens Bank",
        "Truist Bank",
        "Navy Federal Credit Union",
        "Upstart",
        "One Key",
    ]
    assert all(card.description_md == "" for card in cards)
    assert cards[-1].title == "One Key"


def test_business_funding_sequence_default_cards():
    cards = default_cards_for_column("Business Founding Sequence")

    assert len(cards) == 14
    assert cards[0].title == "JP Morgan Chase"
    assert cards[-2].title == "Citi Bank Business"
    assert cards[-1].title == "Paypal Business Loan"
    assert all(card.description_md == "" for card in cards)


def test_completed_default_cards():
    cards = default_cards_for_column("Completed")

    assert len(cards) == 3
    assert all(card.title == "Inquiries" for card in cards)
    assert "THD/CBNA" in cards[0].description_md
    assert "Auto Financing" in cards[1].description_md
    assert cards[2].description_md.count("ALLY FINANCIAL") == 1


def test_create_board_card_from_default_adds_comments():
    db = MagicMock()
    board_list = MagicMock(id=10)
    author = MagicMock(id=7)
    card_def = default_cards_for_column("Client TO DO")[1]

    create_board_card_from_default(
        db,
        board_list=board_list,
        card_def=card_def,
        comment_author=author,
    )

    assert db.add.call_count == 4
    assert db.flush.call_count == 2


def test_apply_default_cards_to_board_list_uses_column_title():
    db = MagicMock()
    board_list = MagicMock(id=10, title="Client TO DO")
    author = MagicMock(id=7)
    db.execute.return_value.scalar_one_or_none.return_value = author

    created = apply_default_cards_to_board_list(db, board_list=board_list)

    assert len(created) == 3
    assert db.add.call_count == 6


def test_merge_missing_default_cards_skips_existing_titles():
    db = MagicMock()
    board_list = MagicMock(id=10, title="Client TO DO")
    author = MagicMock(id=7)

    db.execute.return_value.scalars.return_value.all.side_effect = [
        ["Reportes: Experian, Equifax y TransUnion"],
        [],
    ]
    db.execute.return_value.scalar_one_or_none.return_value = author

    with patch(
        "app.services.default_board_cards.create_board_card_from_default",
        side_effect=lambda *args, **kwargs: MagicMock(title=kwargs["card_def"].title),
    ) as create_mock:
        created = merge_missing_default_cards_to_board_list(db, board_list=board_list)

    assert len(created) == 2
    created_titles = {call.kwargs["card_def"].title for call in create_mock.call_args_list}
    assert created_titles == {
        "Apertura de Cuentas & Freeze",
        "Lista de bancos con relacion",
    }
    assert TAXES_CARD_TITLE not in created_titles


def test_resolve_default_comment_author_prefers_system_user():
    db = MagicMock()
    system_user = MagicMock(email=EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL)
    db.execute.return_value.scalar_one_or_none.return_value = system_user

    assert resolve_default_comment_author(db) is system_user


def test_build_client_personal_data_description():
    db = MagicMock()
    client = MagicMock(
        full_name="Alexis Guanique",
        email="guaniqued@gmail.com",
        phone="+16897771453",
        ssn_encrypted="enc",
        date_of_birth=__import__("datetime").date(1998, 1, 22),
    )
    address = MagicMock(
        street="6867 Belmar Drive",
        city="Orlando",
        state="Florida",
        zip_code="32807",
        residence_since_month=6,
        residence_since_year=2023,
    )
    db.execute.return_value.scalar_one_or_none.side_effect = [address]

    with patch("app.services.clients.ClientService.get_client_ssn", return_value="711-35-8209"):
        description = build_client_personal_data_description(db, client)

    assert "Alexis Guanique" in description
    assert "guaniqued@gmail.com" in description
    assert "711-35-8209" in description
    assert "01/22/1998" in description
    assert "junio del 2023" in description
