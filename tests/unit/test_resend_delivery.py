from unittest.mock import MagicMock, patch

import pytest

from app.services.email.resend_delivery import (
    RESEND_SANDBOX_HINT,
    resolve_email_recipient,
    send_resend_text_email,
)


def test_resolve_email_recipient_redirects_when_configured(monkeypatch):
    monkeypatch.setenv("EMAIL_DEV_REDIRECT_TO", "guaniqued@gmail.com")
    recipient, prefix, original = resolve_email_recipient("cliente@ejemplo.com")
    assert recipient == "guaniqued@gmail.com"
    assert original == "cliente@ejemplo.com"
    assert "cliente@ejemplo.com" in prefix


def test_resolve_email_recipient_ignores_polluted_redirect(monkeypatch):
    """Valores corruptos (p.ej. sync .env pegando la clave siguiente) no deben usarse como `to`."""
    monkeypatch.setenv("EMAIL_DEV_REDIRECT_TO", "sendgrid_api_key=")
    recipient, prefix, original = resolve_email_recipient("cliente@ejemplo.com")
    assert recipient == "cliente@ejemplo.com"
    assert original == "cliente@ejemplo.com"
    assert prefix == ""


def test_send_resend_text_email_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    assert send_resend_text_email(
        intended_recipient="cliente@ejemplo.com",
        subject="Test",
        text="Hola",
    ) is True


@patch("resend.Emails.send")
def test_send_resend_text_email_redirects_recipient(mock_send: MagicMock, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_DEV_REDIRECT_TO", "guaniqued@gmail.com")
    mock_send.return_value = {"id": "email_123"}

    assert send_resend_text_email(
        intended_recipient="cliente@ejemplo.com",
        subject="Test",
        text="Hola",
    ) is True

    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["guaniqued@gmail.com"]
    assert "cliente@ejemplo.com" in call_args["text"]


@patch("resend.Emails.send")
def test_send_resend_text_email_sandbox_error_is_warning_not_exception(
    mock_send: MagicMock,
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

    class FakeResendError(Exception):
        pass

    mock_send.side_effect = FakeResendError(
        "You can only send testing emails to your own email address (guaniqued@gmail.com)."
    )

    with caplog.at_level("WARNING"):
        ok = send_resend_text_email(
            intended_recipient="cliente@ejemplo.com",
            subject="Test",
            text="Hola",
        )

    assert ok is False
    assert RESEND_SANDBOX_HINT in caplog.text
    assert "Traceback" not in caplog.text
