from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.models.client import Client
from app.models.enums import ClientStatus
from app.services.onboarding_reminders import run_onboarding_reminders
from app.workers.inline_scheduler import start_onboarding_reminder_scheduler


def _sample_client(**kwargs) -> Client:
    defaults = {
        "id": 1,
        "first_name": "Ana",
        "last_name": "García",
        "email": "ana@example.com",
        "phone": "+15551234567",
        "status": ClientStatus.EN_CARGA_DATOS.value,
        "registered_by_user_id": 1,
        "approved_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return Client(**defaults)


@pytest.fixture()
def db_session():
    return MagicMock()


def test_run_onboarding_reminders_skips_complete_client(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    client = _sample_client()

    clients_result = MagicMock()
    clients_result.scalars.return_value.all.return_value = [client]
    db_session.execute.return_value = clients_result

    with patch(
        "app.services.onboarding_reminders.analyze_onboarding_gaps",
        return_value=MagicMock(needs_reminder=False, all_pending_labels=lambda: []),
    ):
        summary = run_onboarding_reminders(db_session)

    assert summary == {
        "processed": 1,
        "sent": 0,
        "skipped": 1,
        "failed": 0,
        "dry_run": True,
    }
    db_session.commit.assert_called_once()


def test_run_onboarding_reminders_sends_when_gaps_exist(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    client = _sample_client()

    clients_result = MagicMock()
    clients_result.scalars.return_value.all.return_value = [client]
    portal_result = MagicMock()
    portal_result.scalar_one_or_none.return_value = None
    db_session.execute.side_effect = [clients_result, portal_result]

    gaps = MagicMock(
        needs_reminder=True,
        all_pending_labels=lambda: ["SSN / Seguro Social"],
    )
    with (
        patch("app.services.onboarding_reminders.analyze_onboarding_gaps", return_value=gaps),
        patch("app.services.onboarding_reminders.send_onboarding_reminder_email", return_value=True),
        patch("app.services.onboarding_reminders.send_onboarding_reminder_whatsapp", return_value=False),
        patch("app.services.onboarding_reminders.NotificationService") as mock_notify,
    ):
        summary = run_onboarding_reminders(db_session)

    assert summary["processed"] == 1
    assert summary["sent"] == 1
    assert summary["skipped"] == 0
    assert summary["failed"] == 0
    assert summary["dry_run"] is True
    mock_notify.return_value.notify.assert_not_called()


def test_scheduler_disabled_when_interval_zero():
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        jwt_secret_key="test-secret-key-for-unit-tests-only-32chars",
        onboarding_reminder_interval_minutes=0,
    )
    assert start_onboarding_reminder_scheduler(settings) is None


def test_scheduler_starts_when_interval_positive():
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        jwt_secret_key="test-secret-key-for-unit-tests-only-32chars",
        onboarding_reminder_interval_minutes=5,
    )
    stop_event = start_onboarding_reminder_scheduler(settings)
    assert stop_event is not None
    stop_event.set()
