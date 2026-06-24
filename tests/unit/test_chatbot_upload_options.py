from app.services.chatbot.upload_options import (
    resolve_board_card_id,
    resolve_document_type,
)


def test_resolve_document_type_from_enum_value():
    assert resolve_document_type("DRIVERS_LICENSE_FRONT") == "DRIVERS_LICENSE_FRONT"


def test_resolve_document_type_from_alias():
    assert resolve_document_type("licencia frente") == "DRIVERS_LICENSE_FRONT"
    assert resolve_document_type("ssn") == "SSN_CARD"


def test_resolve_board_card_id_by_reference():
    cards = [{"id": 12, "title": "Subir licencia", "column": "Docs"}]
    assert resolve_board_card_id("tarjeta #12", cards) == 12
    assert resolve_board_card_id("en la tarjeta Subir licencia", cards) == 12
