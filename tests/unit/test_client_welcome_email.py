from unittest.mock import MagicMock, patch

from app.services.email import ClientWelcomeEmailPayload, send_client_welcome_email


def _sample_payload() -> ClientWelcomeEmailPayload:
    return ClientWelcomeEmailPayload(
        recipient_email="cliente@ejemplo.com",
        first_name="Juan",
        temp_password="TempPass123!",
        portal_login_url="https://app.ePoint.com/login",
        client_id=1,
    )


def test_send_client_welcome_email_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert send_client_welcome_email(_sample_payload()) is True


def test_send_client_welcome_email_without_api_key_returns_false(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "")
    assert send_client_welcome_email(_sample_payload()) is False


@patch("resend.Emails.send")
def test_send_client_welcome_email_via_resend(mock_send: MagicMock, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    monkeypatch.setenv("EMAIL_FROM_NAME", "ePoint CRM")
    mock_send.return_value = {"id": "email_123"}

    assert send_client_welcome_email(_sample_payload()) is True
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["cliente@ejemplo.com"]
    assert call_args["subject"] == "¡Bienvenido a ePoint!"
    assert "Juan" in call_args["text"]
    assert "html" in call_args
    assert "Juan" in call_args["html"]
    assert "Ingresar al portal" in call_args["html"]
