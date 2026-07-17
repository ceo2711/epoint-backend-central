from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.prospects import ProspectService


def _make_service() -> ProspectService:
    service = ProspectService.__new__(ProspectService)
    service.db = MagicMock()
    service.audit = MagicMock()
    return service


def test_delete_prospect_requires_admin():
    service = _make_service()
    actor = SimpleNamespace(role=SimpleNamespace(code="SALES_REP"))
    prospect = SimpleNamespace(id=1, email="lead@ejemplo.com")

    with pytest.raises(HTTPException) as exc_info:
        service.delete_prospect(actor=actor, prospect=prospect)

    assert exc_info.value.status_code == 403
    service.db.delete.assert_not_called()
    service.db.commit.assert_not_called()


def test_delete_prospect_admin_deletes_and_logs():
    service = _make_service()
    actor = SimpleNamespace(role=SimpleNamespace(code="ADMIN"))
    prospect = SimpleNamespace(id=7, email="lead@ejemplo.com")

    service.delete_prospect(actor=actor, prospect=prospect)

    service.audit.log.assert_called_once()
    assert service.audit.log.call_args.kwargs["action"] == "PROSPECT_DELETED"
    service.db.delete.assert_called_once_with(prospect)
    service.db.commit.assert_called_once()
