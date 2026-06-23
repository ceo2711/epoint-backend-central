from unittest.mock import MagicMock, patch

from app.services.chatbot.context import ChatbotContextBuilder, REQUIRED_DOCUMENT_TYPES
from app.services.chatbot.service import ChatbotService


def test_required_document_types_are_labeled():
    from app.services.chatbot.context import DOCUMENT_TYPE_LABELS

    for doc_type in REQUIRED_DOCUMENT_TYPES:
        assert doc_type in DOCUMENT_TYPE_LABELS


def test_resolve_client_id_respects_access():
    user = MagicMock()
    user.role.code = "ADMIN"
    user.client_id = None

    db = MagicMock()
    builder = ChatbotContextBuilder(db, user)

    with patch.object(builder.clients, "user_can_access_client", return_value=False):
        assert builder.resolve_client_id("cliente #42", 42) is None

    with patch.object(builder.clients, "user_can_access_client", return_value=True):
        assert builder.resolve_client_id("cliente #42", 42) == 42


def test_system_prompt_uses_sales_template():
    user = MagicMock()
    user.role.code = "SALES_REP"
    user.role.name = "Vendedor"
    user.first_name = "Ana"
    user.last_name = "Perez"
    user.email = "ana@epoint.com"

    service = ChatbotService(MagicMock())
    prompt = service._system_prompt(user, "es", '{"resumen": {}}', pending_action=None)

    assert "registrar nuevos clientes" in prompt or "registrar nuevos" in prompt
    assert "Ana Perez" in prompt
