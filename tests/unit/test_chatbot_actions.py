import re

from app.services.chatbot.actions import (
    ChatbotActionHandler,
    VERIFY_PENDING_PATTERN,
)
from app.services.chatbot.approval_intents import APPROVE_ONE_ID_PATTERN, looks_like_approve_all
from app.services.chatbot.messages import friendly_register_missing, friendly_registration_meta_reply
from app.services.chatbot.registration_intents import REGISTER_INTENT_PATTERN


def test_register_pattern_matches():
    assert REGISTER_INTENT_PATTERN.search("quiero registrar un cliente")
    assert REGISTER_INTENT_PATTERN.search("registrar Alexis Diaz")


def test_register_pattern_matches_without_cliente_keyword():
    assert REGISTER_INTENT_PATTERN.search("registrar a Juan Perez")


def test_cancel_pattern_does_not_match_no_tengo():
    from app.services.chatbot.actions import CANCEL_PATTERN

    assert not CANCEL_PATTERN.match("no tengo el email")
    assert CANCEL_PATTERN.match("cancelar")


def test_looks_like_client_registration():
    handler = ChatbotActionHandler.__new__(ChatbotActionHandler)
    handler.locale = "es"

    assert handler._looks_like_client_registration("juan@mail.com 1131432490")
    assert handler._looks_like_client_registration("Alexis Diaz juan@mail.com")
    assert not handler._looks_like_client_registration("hola como estas")


def test_approve_all_pattern_matches():
    assert looks_like_approve_all("aprobar todos los pendientes")
    assert looks_like_approve_all("apruebalos todos")


def test_approve_all_sets_clients_updated():
    from unittest.mock import MagicMock

    from app.models.client import Client
    from app.models.enums import ClientStatus
    from app.models.user import User

    db = MagicMock()
    handler = ChatbotActionHandler(db, MagicMock())
    handler.locale = "es"
    handler.user = MagicMock()

    client = MagicMock(spec=Client)
    client.id = 104
    client.full_name = "Angela Silva"
    client.email = "angela@example.com"
    client.status = ClientStatus.PENDIENTE_DE_REVISION.value

    advisor = MagicMock(spec=User)
    advisor.first_name = "Ana"
    advisor.last_name = "Lopez"

    approved_client = MagicMock(spec=Client)
    approved_client.id = 104
    approved_client.full_name = "Angela Silva"
    approved_client.email = "angela@example.com"
    approved_client.status = ClientStatus.EN_CARGA_DATOS.value

    handler.clients.bulk_approve_clients = MagicMock(
        return_value=([(approved_client, "TempPass123!")], []),
    )
    db.get.return_value = advisor

    result = handler._approve_all([client])

    assert result.clients_updated is True
    assert result.client_approval is not None
    assert result.client_approvals and len(result.client_approvals) == 1
    assert result.client_approvals[0].temp_password == "TempPass123!"
    handler.clients.bulk_approve_clients.assert_called_once_with(
        actor=handler.user,
        clients=[client],
        send_welcome_notifications=True,
    )


def test_verify_pending_pattern_matches():
    assert VERIFY_PENDING_PATTERN.search("verificar clientes pendientes")


def test_approve_one_extracts_id():
    match = APPROVE_ONE_ID_PATTERN.search("aprobar cliente #67")
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


def test_registration_meta_reply_mentions_multiple_clients():
    reply = friendly_registration_meta_reply("es")
    assert "varios clientes" in reply.lower()
    assert "nombre" in reply.lower()


def test_apply_name_heuristics_skips_meta_question_text():
    handler = ChatbotActionHandler.__new__(ChatbotActionHandler)
    handler.locale = "es"

    merged = handler._apply_name_heuristics(
        "Chat puedes registrar varios clientes al mismo tiempo?",
        {},
    )
    assert not merged.get("first_name")
    assert not merged.get("last_name")


def test_validate_registration_data_flags_empty_phone():
    from unittest.mock import MagicMock

    import psycopg2

    client = MagicMock()
    client.id = 1
    client.first_name = "Ana"
    client.last_name = "Lopez"
    client.email = "ana@example.com"
    client.phone = "12"
    client.source = "WHATSAPP"
    client.merchant_id = 1

    handler = ChatbotActionHandler(MagicMock(), MagicMock())
    handler.clients.find_client_with_email = MagicMock(return_value=None)
    handler.clients.find_client_with_phone = MagicMock(return_value=None)

    issues = handler.validate_registration_data(client)
    assert any("Teléfono" in issue for issue in issues)


def test_pending_approval_query_pattern():
    from app.services.chatbot.actions import PENDING_APPROVAL_QUERY_PATTERN

    assert PENDING_APPROVAL_QUERY_PATTERN.search("Chat tengo algun cliente pendiente de aprobacion")


def test_resolve_merchant_id_ignores_phone_only():
    from unittest.mock import MagicMock

    from app.services.chatbot.registration_options import resolve_merchant_id

    merchant = MagicMock()
    merchant.id = 4
    merchant.code = "epoint-lab"
    merchant.name = "ePoint Lab"

    assert resolve_merchant_id("1131432490", [merchant]) is None
    assert resolve_merchant_id("comercio 4", [merchant]) == 4
    assert resolve_merchant_id("epoint-lab", [merchant]) == 4


def test_approve_client_returns_approval_metadata():
    from unittest.mock import MagicMock

    from app.models.client import Client
    from app.models.enums import ClientStatus
    from app.models.user import User
    from app.schemas.chatbot import ClientApprovalResult

    db = MagicMock()
    handler = ChatbotActionHandler(db, MagicMock())
    handler.locale = "es"
    handler.user = MagicMock()

    client = MagicMock(spec=Client)
    client.id = 42
    client.full_name = "Juan Perez"
    client.email = "juan@mail.com"
    client.status = ClientStatus.EN_CARGA_DATOS.value

    advisor = MagicMock(spec=User)
    advisor.first_name = "Ana"
    advisor.last_name = "Lopez"

    handler.clients.approve_client = MagicMock(return_value=(client, "TempPass123!"))

    result = handler._approve_client(client)

    assert result.client_approval == ClientApprovalResult(
        client_id=42,
        client_name="Juan Perez",
        client_email="juan@mail.com",
        temp_password="TempPass123!",
        advisor_name="Pendiente",
    )
    assert result.client_approvals == [result.client_approval]
    assert result.pending_action is None
    handler.clients.approve_client.assert_called_once_with(
        actor=handler.user,
        client=client,
        send_welcome_notifications=True,
    )
