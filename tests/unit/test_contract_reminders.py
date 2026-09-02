from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.contract_reminders import run_contract_reminders, signer_first_name
from app.services.email.contract_reminder import ContractReminderEmailPayload, send_contract_reminder_email
from app.services.notifications.templates import contract_reminder_email_body


def test_signer_first_name_uses_first_token():
    assert signer_first_name("María Pérez") == "María"
    assert signer_first_name("  ") == "Hola"


def test_send_contract_reminder_email_dry_run(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert send_contract_reminder_email(
        ContractReminderEmailPayload(
            recipient_email="ana@example.com",
            first_name="Ana",
            contract_subject="Contrato de servicios",
            envelope_id=3,
        )
    ) is True


def test_contract_reminder_email_mentions_signing():
    body = contract_reminder_email_body(
        first_name="Ana",
        contract_subject="Contrato de servicios",
    )
    assert "Ana" in body
    assert "Contrato de servicios" in body
    assert "firma" in body.lower()


def test_contract_reminders_skip_within_cooldown():
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    envelope = SimpleNamespace(
        id=9,
        signer_email="ana@example.com",
        signer_name="Ana López",
        subject="Contrato Epoint",
        status="sent",
        sent_at=recent,
        last_contract_reminder_at=recent,
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [envelope]

    with patch("app.services.contract_reminders.send_unsigned_contract_reminder") as send:
        summary = run_contract_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_contract_reminders_send_after_cooldown():
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    envelope = SimpleNamespace(
        id=9,
        signer_email="ana@example.com",
        signer_name="Ana López",
        subject="Contrato Epoint",
        status="sent",
        sent_at=old,
        last_contract_reminder_at=old,
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [envelope]

    with patch(
        "app.services.contract_reminders.send_unsigned_contract_reminder",
        return_value=(True, True),
    ) as send:
        summary = run_contract_reminders(db)

    send.assert_called_once()
    assert summary["sent"] == 1
    assert envelope.last_contract_reminder_at is not None


def test_contract_reminders_skip_created_draft_envelope():
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    envelope = SimpleNamespace(
        id=9,
        signer_email="ana@example.com",
        signer_name="Ana López",
        subject="Contrato Epoint",
        status="created",
        sent_at=old,
        last_contract_reminder_at=None,
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [envelope]

    with patch("app.services.contract_reminders.send_unsigned_contract_reminder") as send:
        summary = run_contract_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_contract_reminders_skip_without_sent_at():
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    envelope = SimpleNamespace(
        id=9,
        signer_email="ana@example.com",
        signer_name="Ana López",
        subject="Contrato Epoint",
        status="sent",
        sent_at=None,
        last_contract_reminder_at=None,
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [envelope]

    with patch("app.services.contract_reminders.send_unsigned_contract_reminder") as send:
        summary = run_contract_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0
