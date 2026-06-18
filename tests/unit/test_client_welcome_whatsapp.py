from unittest.mock import MagicMock, patch

from app.services.whatsapp import ClientWelcomeWhatsAppPayload, send_client_welcome_whatsapp


def _sample_payload() -> ClientWelcomeWhatsAppPayload:
    return ClientWelcomeWhatsAppPayload(
        recipient_phone="1131432490",
        first_name="Juan",
        email="cliente@ejemplo.com",
        temp_password="TempPass123!",
        portal_login_url="https://app.ePoint.com/login",
        client_id=1,
    )


def test_send_client_welcome_whatsapp_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    assert send_client_welcome_whatsapp(_sample_payload()) is True


def test_send_client_welcome_whatsapp_without_phone_returns_false():
    payload = ClientWelcomeWhatsAppPayload(
        recipient_phone="",
        first_name="Juan",
        email="cliente@ejemplo.com",
        temp_password="TempPass123!",
        portal_login_url="https://app.ePoint.com/login",
    )
    assert send_client_welcome_whatsapp(payload) is False


@patch("twilio.rest.Client")
def test_send_client_welcome_whatsapp_via_twilio(mock_client_cls: MagicMock, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setenv("TWILIO_WHATSAPP_CLIENT_APPROVED_CONTENT_SID", "HXtest")
    mock_client_cls.return_value.messages.create.return_value = MagicMock(
        sid="SM123",
        status="queued",
    )

    assert send_client_welcome_whatsapp(_sample_payload()) is True
    mock_client_cls.return_value.messages.create.assert_called_once()
