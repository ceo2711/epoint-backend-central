"""PAYMENT_TEST fuerza modo de pago simulado aunque haya proveedores configurados."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.payments.service import PaymentService


def _service(*, payment_test: bool, authorize: bool = False, paypal: bool = False) -> PaymentService:
    settings = SimpleNamespace(
        payment_test=payment_test,
        payments_enabled=True,
        payments_default_provider_normalized="authorize",
        payments_webhook_base_url=None,
        portal_base_url="http://localhost:3000",
    )
    svc = PaymentService.__new__(PaymentService)
    svc.db = MagicMock()
    svc.settings = settings
    svc.authorize = SimpleNamespace(is_configured=authorize)
    svc.paypal = SimpleNamespace(is_configured=paypal)
    return svc


def test_stub_mode_true_when_payment_test_even_if_providers_configured():
    svc = _service(payment_test=True, authorize=True, paypal=True)
    assert svc.stub_mode is True


def test_stub_mode_false_when_payment_test_off_and_provider_configured():
    svc = _service(payment_test=False, authorize=True, paypal=False)
    assert svc.stub_mode is False


def test_stub_mode_true_when_no_providers_even_if_payment_test_off():
    svc = _service(payment_test=False, authorize=False, paypal=False)
    assert svc.stub_mode is True
