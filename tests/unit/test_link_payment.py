"""No se puede vincular un link de pago que ya fue pagado."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.payment_link import PaymentLinkStatus
from app.services.prospects import ProspectService


def _actor():
    return SimpleNamespace(id=7, role=SimpleNamespace(code="SALES_REP"))


def _prospect():
    return SimpleNamespace(id=1, email="lead@example.com", converted_client_id=None)


def _link(**kwargs):
    defaults = {
        "id": 9,
        "status": PaymentLinkStatus.PENDING.value,
        "customer_email": "lead@example.com",
        "created_by_user_id": 7,
        "prospect_id": None,
        "currency": "USD",
        "amount": 100,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_link_payment_rejects_paid_link():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    svc.db.get.return_value = _link(status=PaymentLinkStatus.PAID.value)

    with pytest.raises(HTTPException) as exc:
        svc.link_payment_link(actor=_actor(), prospect=_prospect(), payment_link_id=9)

    assert exc.value.status_code == 400
    assert "pendiente" in exc.value.detail.lower() or "pagad" in exc.value.detail.lower()


def test_link_payment_rejects_cancelled_link():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    svc.db.get.return_value = _link(status=PaymentLinkStatus.CANCELLED.value)

    with pytest.raises(HTTPException) as exc:
        svc.link_payment_link(actor=_actor(), prospect=_prospect(), payment_link_id=9)

    assert exc.value.status_code == 400


def test_link_payment_rejects_link_already_tied_to_another_prospect():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    svc.db.get.return_value = _link(prospect_id=99)

    with pytest.raises(HTTPException) as exc:
        svc.link_payment_link(actor=_actor(), prospect=_prospect(), payment_link_id=9)

    assert exc.value.status_code == 400
    assert "otro prospecto" in exc.value.detail.lower()
