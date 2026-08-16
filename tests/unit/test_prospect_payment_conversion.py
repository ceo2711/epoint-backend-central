"""Conversión de prospecto: las tres condiciones son siempre obligatorias."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.enums import ProspectStatus
from app.models.payment_link import PaymentLinkStatus
from app.services.prospects import ProspectService


def _prospect(**kwargs):
    defaults = {
        "id": 1,
        "status": ProspectStatus.PAGO_COMPLETADO.value,
        "payment_link_id": 10,
        "calendly_event_id": None,
        "converted_client_id": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _paid_service() -> ProspectService:
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    svc.db.get.return_value = SimpleNamespace(status=PaymentLinkStatus.PAID.value)
    return svc


def test_ready_for_conversion_false_without_seller_contact():
    svc = _paid_service()
    svc._seller_marked_contacted = MagicMock(return_value=False)
    svc.list_linked_envelopes = MagicMock(return_value=[SimpleNamespace(status="completed")])
    prospect = _prospect()

    assert svc._ready_for_conversion(prospect) is False
    svc._seller_marked_contacted.assert_called_once_with(prospect)
    svc.list_linked_envelopes.assert_not_called()


def test_ready_for_conversion_false_without_signed_contract():
    svc = _paid_service()
    svc._seller_marked_contacted = MagicMock(return_value=True)
    svc.list_linked_envelopes = MagicMock(return_value=[])
    prospect = _prospect()

    assert svc._ready_for_conversion(prospect) is False


def test_ready_for_conversion_true_with_contact_signed_contract_and_payment():
    svc = _paid_service()
    svc._seller_marked_contacted = MagicMock(return_value=True)
    svc.list_linked_envelopes = MagicMock(
        return_value=[SimpleNamespace(status="completed")],
    )
    prospect = _prospect()

    assert svc._ready_for_conversion(prospect) is True


def test_seller_marked_contacted_false_when_only_pago_completado():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    svc.db.execute.return_value.scalar_one_or_none.return_value = None
    prospect = _prospect(status=ProspectStatus.PAGO_COMPLETADO.value)

    assert svc._seller_marked_contacted(prospect) is False


def test_seller_marked_contacted_true_from_lead_contactado_status():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    prospect = _prospect(status=ProspectStatus.LEAD_CONTACTADO.value)

    assert svc._seller_marked_contacted(prospect) is True
    svc.db.execute.assert_not_called()
