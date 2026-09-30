from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.payment_methods import label_for_payment_method, parse_payment_methods
from app.schemas.payment import PaymentLinkCreate
from app.services.payments.service import PaymentService


def test_parse_payment_methods_reads_code_and_label():
    options = parse_payment_methods("authorize:Authorize.net, paypal:PayPal, zelle:Zelle")
    assert [(item.code, item.label) for item in options] == [
        ("authorize", "Authorize.net"),
        ("paypal", "PayPal"),
        ("zelle", "Zelle"),
    ]


def test_parse_payment_methods_falls_back_when_empty():
    options = parse_payment_methods("   ")
    assert [item.code for item in options] == ["authorize", "paypal"]


def test_parse_payment_methods_skips_invalid_codes():
    options = parse_payment_methods("esta etiqueta es demasiado larga para el codigo:X,zelle:Zelle")
    assert [item.code for item in options] == ["zelle"]


def test_label_uses_configured_name():
    options = parse_payment_methods("zelle:Zelle Business")
    assert label_for_payment_method("zelle", options) == "Zelle Business"
    assert label_for_payment_method("paypal", options) == "PayPal"


def _seller():
    return SimpleNamespace(id=4, role=SimpleNamespace(code="SALES_REP"))


def _payload(provider: str) -> PaymentLinkCreate:
    return PaymentLinkCreate(
        customer_first_name="Ana",
        customer_last_name="Lopez",
        customer_email="ana@example.com",
        customer_phone="5551234567",
        amount=Decimal("3000.00"),
        provider=provider,
    )


def test_record_accepts_method_declared_in_env():
    svc = PaymentService(MagicMock())
    svc.ensure_access = MagicMock()
    svc.settings = svc.settings.model_copy(update={"payment_methods": "zelle:Zelle,paypal:PayPal"})
    captured: dict = {}

    def apply(link, charged=None):
        link.amount_paid = charged
        link.status = "paid"
        captured["provider"] = link.provider

    svc._apply_received_payment = apply
    svc._to_response = lambda link: SimpleNamespace(status=link.status, provider=link.provider)

    result = svc.create_link(_seller(), _payload("zelle"), merchant_id=1)
    assert result.email_sent is False
    assert captured["provider"] == "zelle"


def test_record_rejects_method_not_in_env():
    svc = PaymentService(MagicMock())
    svc.ensure_access = MagicMock()
    svc.settings = svc.settings.model_copy(
        update={"payment_methods": "authorize:Authorize.net,paypal:PayPal"}
    )
    with pytest.raises(HTTPException) as exc:
        svc.create_link(_seller(), _payload("cash"), merchant_id=1)
    assert exc.value.status_code == 400


def test_config_lists_env_methods():
    svc = PaymentService(MagicMock())
    svc.ensure_access = MagicMock()
    svc.settings = svc.settings.model_copy(
        update={
            "payment_methods": "zelle:Zelle,paypal:PayPal",
            "payments_default_provider": "zelle",
        }
    )
    config = svc.get_config(MagicMock())
    assert [(item.provider, item.label) for item in config.providers] == [
        ("zelle", "Zelle"),
        ("paypal", "PayPal"),
    ]
    assert config.default_provider == "zelle"
