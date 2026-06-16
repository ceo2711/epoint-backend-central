from app.services.email import ClientWelcomeEmailPayload, send_client_welcome_email


def test_send_client_welcome_email_stub_returns_true():
    payload = ClientWelcomeEmailPayload(
        recipient_email="cliente@ejemplo.com",
        first_name="Juan",
        temp_password="TempPass123!",
        portal_login_url="https://app.ePoint.com/login",
        client_id=1,
    )
    assert send_client_welcome_email(payload) is True
