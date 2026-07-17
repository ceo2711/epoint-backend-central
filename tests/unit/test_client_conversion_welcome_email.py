from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.email.client_conversion_welcome import (
    ClientConversionWelcomeEmailPayload,
    send_client_conversion_welcome_email,
)


def _sample_payload() -> ClientConversionWelcomeEmailPayload:
    return ClientConversionWelcomeEmailPayload(
        recipient_email="cliente@ejemplo.com",
        first_name="María",
        amount=Decimal("150.00"),
        currency="USD",
        client_id=42,
        merchant_name="Comercio Demo",
    )


def test_send_client_conversion_welcome_email_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    assert send_client_conversion_welcome_email(_sample_payload()) is True


def test_send_client_conversion_welcome_email_without_api_key_returns_false(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "")

    assert send_client_conversion_welcome_email(_sample_payload()) is False


@patch("resend.Emails.send")
def test_send_client_conversion_welcome_email_via_resend(mock_send: MagicMock, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    monkeypatch.setenv("EMAIL_FROM_NAME", "ePoint CRM")
    mock_send.return_value = {"id": "email_789"}

    assert send_client_conversion_welcome_email(_sample_payload()) is True
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["cliente@ejemplo.com"]
    assert call_args["subject"] == "¡Bienvenido/a a ePoint! Tu perfil está en revisión"
    assert "María" in call_args["text"]
    assert "USD 150.00" in call_args["text"]
    assert "equipo de Onboarding" in call_args["text"]
    assert "Tu perfil pasa a revisión" in call_args["html"]
