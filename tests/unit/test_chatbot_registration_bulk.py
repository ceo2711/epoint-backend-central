import pytest
from unittest.mock import MagicMock

from app.models.client import Client
from app.services.chatbot.actions import ChatbotActionHandler
from app.services.chatbot.registration_bulk import (
    looks_like_bulk_registration,
    looks_like_structured_registration_block,
    parse_bulk_registration_blocks,
    split_full_name,
)


SAMPLE_BULK_MESSAGE = """
Datos personales
Nombre completo: Ramon Silva Paez
Email: guaniqued@gmail.com
Numero de telefono: 7542489337
merchant: db-studio

Datos personales
Nombre completo: Angela Daniela Silva Paez
Email: guaniqued@gmail.com
Numero de telefono: 7542489337
merchant: db-studio

Datos personales
Nombre completo: Jesus Silva Paez
Email: guaniqued@gmail.com
Numero de telefono: 7542489337
merchant: db-studio
"""


@pytest.fixture
def merchant():
    m = MagicMock()
    m.id = 3
    m.code = "db-studio"
    m.name = "DB Studio"
    m.is_active = True
    return m


def test_split_full_name():
    assert split_full_name("Ramon Silva Paez") == ("Ramon", "Silva Paez")
    assert split_full_name("Angela Daniela Silva Paez") == ("Angela", "Daniela Silva Paez")


def test_looks_like_bulk_registration(merchant):
    assert looks_like_bulk_registration(SAMPLE_BULK_MESSAGE)
    assert looks_like_structured_registration_block(SAMPLE_BULK_MESSAGE)


def test_parse_bulk_registration_blocks(merchant):
    blocks = parse_bulk_registration_blocks(SAMPLE_BULK_MESSAGE, [merchant])
    assert len(blocks) == 3
    assert blocks[0].draft["first_name"] == "Ramon"
    assert blocks[0].draft["last_name"] == "Silva Paez"
    assert blocks[0].draft["email"] == "guaniqued@gmail.com"
    assert blocks[0].draft["phone"] == "7542489337"
    assert blocks[0].draft["merchant_id"] == 3
    assert blocks[1].display_name == "Angela Daniela Silva Paez"


def test_parse_single_structured_block(merchant):
    single = """
Datos personales
Nombre completo: Juan Perez
Email: juan@mail.com
Numero de telefono: 1134567890
merchant: db-studio
"""
    blocks = parse_bulk_registration_blocks(single, [merchant])
    assert len(blocks) == 1
    assert blocks[0].draft["email"] == "juan@mail.com"


INLINE_BULK_MESSAGE = """
Esta es la informacion:

Cliente 1 Datos personales Nombre completo: Alexis Antonio Guanique Diaz Email: guaniqued@gmail.com Numero de telefono: 8132957406 merchant: epoint-credits

Cliente 2 Datos personales Nombre completo: Valentina Sofía Herrera Campos Email: vherrera.pruebas28@gmail.com Numero de telefono: 6893724150 merchant: epoint-credits

Cliente 3 Datos personales Nombre completo: Matías Emanuel Correa Delgado Email: mcorrea.demo53@gmail.com Numero de telefono: 9546218374 merchant: epoint-credits
"""


def test_parse_inline_cliente_blocks(merchant):
    merchant.code = "epoint-credits"
    merchant.name = "Epoint Credits"
    blocks = parse_bulk_registration_blocks(INLINE_BULK_MESSAGE, [merchant])
    assert len(blocks) == 3
    assert blocks[0].draft["first_name"] == "Alexis"
    assert blocks[0].draft["last_name"] == "Antonio Guanique Diaz"
    assert blocks[0].draft["email"] == "guaniqued@gmail.com"
    assert blocks[0].draft["phone"] == "8132957406"
    assert blocks[0].draft["merchant_id"] == 3
    assert blocks[1].draft["email"] == "vherrera.pruebas28@gmail.com"
    assert blocks[2].draft["phone"] == "9546218374"
    assert blocks[0].errors == []


def test_bulk_register_saves_first_and_reports_duplicate_failures(merchant):
    from fastapi import HTTPException

    db = MagicMock()
    handler = ChatbotActionHandler(db, MagicMock())
    handler.locale = "es"
    handler.user = MagicMock()
    handler.permissions = {"clients:create", "clients:read"}
    handler._list_active_merchants = MagicMock(return_value=[merchant])

    created = MagicMock(spec=Client)
    created.id = 101
    created.full_name = "Ramon Silva Paez"
    created.email = "guaniqued@gmail.com"
    created.phone = "7542489337"

    def create_side_effect(**kwargs):
        if kwargs["first_name"] == "Ramon":
            return created, None
        raise HTTPException(
            status_code=409,
            detail="El email ya está registrado por Ramon Silva Paez (cliente #101)",
        )

    handler.clients.create_client = MagicMock(side_effect=create_side_effect)
    db.get.return_value = created

    import asyncio

    result = asyncio.run(handler._create_clients_from_bulk(SAMPLE_BULK_MESSAGE))

    assert result.clients_updated is True
    assert handler.clients.create_client.call_count == 3
    assert "Ramon Silva Paez" in result.reply
    assert "Angela Daniela Silva Paez" in result.reply
    assert "Jesus Silva Paez" in result.reply
    assert "email" in result.reply.lower() or "Email" in result.reply
