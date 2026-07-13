from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.client import Client
from app.services.clients import ClientService


@pytest.fixture
def service():
    db = MagicMock()
    svc = ClientService(db)
    svc.user_can_access_client = MagicMock(return_value=True)
    svc.delete_client = MagicMock()
    return svc


def test_bulk_delete_clients_success(service):
    client = MagicMock(spec=Client)
    service.db.get.return_value = client

    result = service.bulk_delete_clients(actor=MagicMock(), client_ids=[1, 2, 2])

    assert result["deleted_ids"] == [1, 2]
    assert result["failures"] == []
    assert service.delete_client.call_count == 2


def test_bulk_delete_clients_reports_unauthorized(service):
    service.user_can_access_client.side_effect = lambda _actor, client_id, merchant_id=None: client_id == 1
    client = MagicMock(spec=Client)
    service.db.get.return_value = client

    result = service.bulk_delete_clients(actor=MagicMock(), client_ids=[1, 2])

    assert result["deleted_ids"] == [1]
    assert len(result["failures"]) == 1
    assert result["failures"][0]["client_id"] == 2


def test_bulk_delete_clients_reports_http_errors(service):
    client = MagicMock(spec=Client)
    service.db.get.return_value = client
    service.delete_client.side_effect = HTTPException(status_code=409, detail="Conflicto")

    result = service.bulk_delete_clients(actor=MagicMock(), client_ids=[5])

    assert result["deleted_ids"] == []
    assert result["failures"][0]["reason"] == "Conflicto"
