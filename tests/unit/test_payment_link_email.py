from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.email.payment_link import PaymentLinkEmailPayload, send_payment_link_email


def _sample_payload() -> PaymentLinkEmailPayload:
    return PaymentLinkEmailPayload(
        recipient_email="cliente@ejemplo.com",
        first_name="María",
        amount=Decimal("150.00"),
        currency="USD",
        payment_url="https://app.ePoint.com/pagar/abc123",
        provider_label="Authorize.net",
        payment_link_id=42,
        description="Servicio de consultoría",
    )


def test_send_payment_link_email_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert send_payment_link_email(_sample_payload()) is True


def test_send_payment_link_email_without_api_key_returns_false(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "")
    assert send_payment_link_email(_sample_payload()) is False


@patch("resend.Emails.send")
def test_send_payment_link_email_via_resend(mock_send: MagicMock, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    monkeypatch.setenv("EMAIL_FROM_NAME", "Epoint Corporation")
    mock_send.return_value = {"id": "email_456"}

    assert send_payment_link_email(_sample_payload()) is True
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["cliente@ejemplo.com"]
    assert call_args["subject"] == "Tu link de pago Epoint"
    assert "María" in call_args["text"]
    assert "USD 150.00" in call_args["text"]
    assert "https://app.ePoint.com/pagar/abc123" in call_args["text"]
    assert "html" in call_args
    assert "Completar pago" in call_args["html"]
