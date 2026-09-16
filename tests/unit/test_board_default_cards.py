from unittest.mock import MagicMock, patch

from app.constants.kanban_columns import (
    BUSINESS_FUNDING_SEQUENCE,
    BUSINESS_FUNDING_SEQUENCE_2,
    KANBAN_COLUMN_TITLES,
    PERSONAL_FUNDING_SEQUENCE,
    PERSONAL_FUNDING_SEQUENCE_2,
)
from app.constants.default_board_cards import (
    ACCOUNTS_CARD_TITLE,
    BANKS_CARD_TITLE,
    CLARITY_CARD_TITLE,
    EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL,
    FUNDER_BUSINESS_SEQUENCE_TITLES,
    FUNDER_PERSONAL_SEQUENCE_TITLES,
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


def test_kanban_template_columns_match_new_layout():
    assert KANBAN_COLUMN_TITLES == (
        "Client TO DO",
        "Credenciales",
        "Ideas a realizar",
        "Experian",
        "Equifax",
        "Transunion",
        PERSONAL_FUNDING_SEQUENCE,
        BUSINESS_FUNDING_SEQUENCE,
    )


def test_client_todo_default_cards():
    cards = default_cards_for_column("Client TO DO")

    assert len(cards) == 4
    assert [card.title for card in cards] == [
        "Reportes: Experian, Equifax y TransUnion",
        ACCOUNTS_CARD_TITLE,
        BANKS_CARD_TITLE,
        TAXES_CARD_TITLE,
    ]
    assert cards[0].requires_file_upload is True
    assert cards[1].requires_credentials is False
    assert cards[1].comments == ()
    assert "experian.com" in cards[0].description_md
    assert "Buy your report" in cards[0].description_md
    assert "chexsystems.com" in cards[1].description_md
    assert "1-800-456-1244" not in cards[1].description_md
    assert "Bancos activos" in cards[2].description_md
    assert cards[3].requires_file_upload is True
    assert "no es obligatoria" in cards[3].description_md
    assert TAXES_CARD_COLUMN == "Client TO DO"
    assert is_optional_onboarding_card(TAXES_CARD_TITLE) is True
    assert is_optional_onboarding_card(ACCOUNTS_CARD_TITLE) is False


def test_ideas_experian_equifax_transunion_start_empty():
    assert default_cards_for_column("Ideas a realizar") == ()
    assert default_cards_for_column("Experian") == ()
    assert default_cards_for_column("Equifax") == ()
    assert default_cards_for_column("Transunion") == ()
    assert default_cards_for_column("Completed") == ()


def test_credenciales_default_cards():
    cards = default_cards_for_column("Credenciales")

    assert len(cards) == 6
    assert [card.title for card in cards] == [
        "Experian",
        "Equifax",
        "TransUnion",
        "ChexSystems",
        "Innovis",
        CLARITY_CARD_TITLE,
    ]
    assert cards[-1].requires_file_upload is True
    assert cards[0].requires_credentials is True
    assert cards[1].requires_credentials is True
    assert cards[2].requires_credentials is True
    assert "formulario cifrado" in cards[0].description_md
    assert "ACCESS YOUR CLARITY CREDIT REPORT" in cards[-1].description_md
    assert "Datos personales" not in {card.title for card in cards}


def test_funding_sequences_have_no_default_cards():
    assert default_cards_for_column(PERSONAL_FUNDING_SEQUENCE) == ()
    assert default_cards_for_column(PERSONAL_FUNDING_SEQUENCE_2) == ()
    assert default_cards_for_column(BUSINESS_FUNDING_SEQUENCE) == ()
    assert default_cards_for_column(BUSINESS_FUNDING_SEQUENCE_2) == ()
    assert default_cards_for_column("Personal Fonding Sequence (2)") == ()
    assert default_cards_for_column("Business Founding Sequence") == ()
    assert default_cards_for_column("Business Founding Sequence (2)") == ()
    assert len(FUNDER_PERSONAL_SEQUENCE_TITLES) > 0
    assert len(FUNDER_BUSINESS_SEQUENCE_TITLES) > 0


def test_create_board_card_from_default_creates_card():
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

    assert db.add.call_count == 1
    assert db.flush.call_count == 2


def test_apply_default_cards_to_board_list_uses_column_title():
    db = MagicMock()
    board_list = MagicMock(id=10, title="Client TO DO")
    author = MagicMock(id=7)
    db.execute.return_value.scalar_one_or_none.return_value = author

    created = apply_default_cards_to_board_list(db, board_list=board_list)

    assert len(created) == 4
    assert db.add.call_count == 4


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

    assert len(created) == 3
    created_titles = {call.kwargs["card_def"].title for call in create_mock.call_args_list}
    assert created_titles == {
        ACCOUNTS_CARD_TITLE,
        BANKS_CARD_TITLE,
        TAXES_CARD_TITLE,
    }


def test_merge_missing_default_cards_treats_legacy_titles_as_present():
    db = MagicMock()
    board_list = MagicMock(id=10, title="Client TO DO")
    author = MagicMock(id=7)

    db.execute.return_value.scalars.return_value.all.side_effect = [
        ["Apertura de Cuentas & Freeze", "Lista de bancos con relacion"],
        [],
    ]
    db.execute.return_value.scalar_one_or_none.return_value = author

    with patch(
        "app.services.default_board_cards.create_board_card_from_default",
        side_effect=lambda *args, **kwargs: MagicMock(title=kwargs["card_def"].title),
    ) as create_mock:
        created = merge_missing_default_cards_to_board_list(db, board_list=board_list)

    created_titles = {call.kwargs["card_def"].title for call in create_mock.call_args_list}
    assert ACCOUNTS_CARD_TITLE not in created_titles
    assert BANKS_CARD_TITLE not in created_titles
    assert "Reportes: Experian, Equifax y TransUnion" in created_titles
    assert TAXES_CARD_TITLE in created_titles
    assert len(created) == 2


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
