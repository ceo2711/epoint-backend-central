from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.email import StaffWelcomeEmailPayload, send_staff_welcome_email
from app.services.email.staff_welcome import notify_staff_account_created, staff_role_line
from app.services.notifications.templates import staff_welcome_email_body


def _sample_payload() -> StaffWelcomeEmailPayload:
    return StaffWelcomeEmailPayload(
        recipient_email="alexis@eberthscapital.com",
        first_name="Alexis",
        temp_password="alexis123",
        login_url="https://www.epointcorporation.com/login",
        role_line="Tu perfil: Líder de área · Onboarding · Headquarters.",
        user_id=12,
    )


def test_staff_welcome_email_body_includes_credentials():
    body = staff_welcome_email_body(
        first_name="Alexis",
        email="alexis@eberthscapital.com",
        temp_password="alexis123",
        login_url="https://www.epointcorporation.com/login",
        role_line="Tu perfil: Líder de área · Onboarding · Headquarters.",
    )
    assert "Alexis" in body
    assert "alexis@eberthscapital.com" in body
    assert "alexis123" in body
    assert "https://www.epointcorporation.com/login" in body
    assert "Líder de área" in body
    assert "cambiar la contraseña temporal" in body


def test_staff_role_line():
    user = SimpleNamespace(
        role=SimpleNamespace(name="Líder de área"),
        area=SimpleNamespace(name="Onboarding"),
        sede=SimpleNamespace(name="Headquarters"),
    )
    assert staff_role_line(user) == "Tu perfil: Líder de área · Onboarding · Headquarters."


def test_send_staff_welcome_email_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert send_staff_welcome_email(_sample_payload()) is True


def test_send_staff_welcome_email_without_api_key_returns_false(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "")
    assert send_staff_welcome_email(_sample_payload()) is False


@patch("resend.Emails.send")
def test_send_staff_welcome_email_via_resend(mock_send: MagicMock, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    monkeypatch.setenv("EMAIL_FROM_NAME", "Epoint Corporation")
    mock_send.return_value = {"id": "email_staff_1"}

    assert send_staff_welcome_email(_sample_payload()) is True
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["alexis@eberthscapital.com"]
    assert call_args["subject"] == "Tu cuenta de Epoint está lista"
    assert "Alexis" in call_args["text"]
    assert "html" in call_args
    assert "Ingresar" in call_args["html"]
    assert "google-play-badge" not in call_args["html"]


def test_notify_staff_account_created_does_not_raise(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    user = SimpleNamespace(
        id=1,
        email="staff@epoint.com",
        first_name="Ana",
        role=SimpleNamespace(name="Asesor"),
        area=SimpleNamespace(name="Onboarding"),
        sede=SimpleNamespace(name="Headquarters"),
    )
    assert notify_staff_account_created(user, "temp-pass") is True
