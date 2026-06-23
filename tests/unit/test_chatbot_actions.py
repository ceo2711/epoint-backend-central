import re

from app.services.chatbot.actions import (
    APPROVE_ALL_PATTERN,
    APPROVE_ONE_PATTERN,
    ChatbotActionHandler,
    REGISTER_INTENT_PATTERN,
    VERIFY_PENDING_PATTERN,
)
from app.services.chatbot.messages import friendly_register_missing


def test_register_pattern_matches():
    assert REGISTER_INTENT_PATTERN.search("quiero registrar un cliente")
    assert REGISTER_INTENT_PATTERN.search("registrar Alexis Diaz")


def test_register_pattern_matches_without_cliente_keyword():
    assert REGISTER_INTENT_PATTERN.search("registrar a Juan Perez")


def test_approve_all_pattern_matches():
    assert APPROVE_ALL_PATTERN.search("aprobar todos los pendientes")


def test_verify_pending_pattern_matches():
    assert VERIFY_PENDING_PATTERN.search("verificar clientes pendientes")


def test_approve_one_extracts_id():
    match = APPROVE_ONE_PATTERN.search("aprobar cliente #67")
    assert match
    assert match.group(1) == "67"


def test_extract_name_from_natural_message():
    handler = ChatbotActionHandler.__new__(ChatbotActionHandler)
    handler.locale = "es"

    first, last = handler._extract_name_from_message("registrar Alexis Diaz")
    assert first == "Alexis"
    assert last == "Diaz"

    first, last = handler._extract_name_from_message("registrar a Maria Laura Gomez")
    assert first == "Maria"
    assert last == "Laura Gomez"


def test_friendly_register_missing_keeps_name():
    reply = friendly_register_missing(
        "es",
        {"first_name": "Alexis", "last_name": "Diaz"},
    )
    assert "Alexis Diaz" in reply
    assert "email" in reply.lower()
    assert "Register client" not in reply


def test_validate_registration_data_flags_empty_phone():
    from unittest.mock import MagicMock

    import psycopg2

    client = MagicMock()
    client.id = 1
    client.first_name = "Ana"
    client.last_name = "Lopez"
    client.email = "ana@example.com"
    client.phone = "12"

    handler = ChatbotActionHandler(MagicMock(), MagicMock())
    handler.clients.find_client_with_email = MagicMock(return_value=None)
    handler.clients.find_client_with_phone = MagicMock(return_value=None)

    issues = handler.validate_registration_data(client)
    assert any("Teléfono" in issue for issue in issues)
