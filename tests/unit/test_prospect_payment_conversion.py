"""Conversión de prospecto tras pago: PAYMENT_TEST y requisitos normales."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


def test_ready_for_conversion_with_payment_test_only_needs_paid_link():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    link = SimpleNamespace(status=PaymentLinkStatus.PAID.value)
    svc.db.get.return_value = link
    prospect = _prospect()

    with patch("app.core.config.get_settings", return_value=SimpleNamespace(payment_test=True)):
        assert svc._ready_for_conversion(prospect) is True


def test_ready_for_conversion_without_payment_test_needs_meeting_and_contract():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    link = SimpleNamespace(status=PaymentLinkStatus.PAID.value)
    svc.db.get.return_value = link
    svc.list_linked_envelopes = MagicMock(return_value=[])
    prospect = _prospect(calendly_event_id=None)

    with patch("app.core.config.get_settings", return_value=SimpleNamespace(payment_test=False)):
        assert svc._ready_for_conversion(prospect) is False
