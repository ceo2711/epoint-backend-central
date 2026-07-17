from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.prospects import ProspectService


def _service_with_rows(clients: list, prospects: list) -> ProspectService:
    """Servicio con db mockeada: primera consulta devuelve clientes, segunda prospectos."""
    service = ProspectService.__new__(ProspectService)
    service.db = MagicMock()

    def execute(_query):
        result = MagicMock()
        rows = execute.calls.pop(0)
        result.scalars.return_value = rows
        result.scalar_one_or_none.return_value = rows[0] if rows else None
        return result

    execute.calls = [clients, prospects]
    service.db.execute.side_effect = execute
    return service


def _person(phone: str = "+5491131432490", email: str = "dup@ejemplo.com"):
    return SimpleNamespace(
        id=7,
        phone=phone,
        email=email,
        full_name="Juan Pérez",
    )


@patch("app.core.config.get_settings")
def test_phone_conflict_with_existing_client_raises_409(mock_settings: MagicMock):
    mock_settings.return_value = SimpleNamespace(whatsapp_default_country_code="54")
    service = _service_with_rows(clients=[_person()], prospects=[])

    with pytest.raises(HTTPException) as exc:
        service._assert_phone_available("011 3143-2490", merchant_id=1)

    assert exc.value.status_code == 409
    assert "cliente" in exc.value.detail


@patch("app.core.config.get_settings")
def test_phone_conflict_with_active_prospect_raises_409(mock_settings: MagicMock):
    mock_settings.return_value = SimpleNamespace(whatsapp_default_country_code="54")
    service = _service_with_rows(clients=[], prospects=[_person()])

    with pytest.raises(HTTPException) as exc:
        service._assert_phone_available("+5491131432490", merchant_id=1)

    assert exc.value.status_code == 409
    assert "prospecto" in exc.value.detail


@patch("app.core.config.get_settings")
def test_phone_without_conflict_passes(mock_settings: MagicMock):
    mock_settings.return_value = SimpleNamespace(whatsapp_default_country_code="54")
    service = _service_with_rows(clients=[_person(phone="+5491100000001")], prospects=[])

    service._assert_phone_available("+5491131432490", merchant_id=1)


@patch("app.core.config.get_settings")
def test_check_contact_availability_reports_phone_conflict(mock_settings: MagicMock):
    mock_settings.return_value = SimpleNamespace(whatsapp_default_country_code="54")
    service = _service_with_rows(clients=[], prospects=[_person()])

    result = service.check_contact_availability(phone="1131432490", merchant_id=1)

    assert result["available"] is False
    assert result["phone"]["kind"] == "prospect"
    assert result["phone"]["client_name"] == "Juan Pérez"
    assert result["email"] is None
