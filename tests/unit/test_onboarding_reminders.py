from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.models.client import Client
from app.models.enums import ClientStatus
from app.models.user import User
from app.services.onboarding_reminders import run_onboarding_reminders
from app.workers.inline_scheduler import start_onboarding_reminder_scheduler


def _sample_client(**kwargs) -> Client:
    old = datetime.now(timezone.utc) - timedelta(days=100)
    defaults = {
        "id": 1,
        "first_name": "Ana",
        "last_name": "García",
        "email": "ana@example.com",
        "phone": "+15551234567",
        "status": ClientStatus.EN_CARGA_DATOS.value,
        "registered_by_user_id": 1,
        "approved_at": old,
        "created_at": old,
    }
    defaults.update(kwargs)
    return Client(**defaults)


@pytest.fixture()
def db_session():
    return MagicMock()


def _sample_portal_user(client: Client) -> User:
    return User(
        id=10,
        email=client.email,
        password_hash="hash",
        first_name=client.first_name,
        last_name=client.last_name,
        role_id=1,
        client_id=client.id,
        is_active=True,
    )


def test_run_onboarding_reminders_skips_complete_client(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    client = _sample_client()

    with (
        patch(
            "app.services.onboarding_reminders.fetch_clients_with_active_portal_user",
            return_value=[(client, _sample_portal_user(client))],
        ),
        patch(
            "app.services.onboarding_reminders.analyze_onboarding_gaps",
            return_value=MagicMock(needs_reminder=False, all_pending_labels=lambda: []),
        ),
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
    portal_user = _sample_portal_user(client)

    gaps = MagicMock(
        needs_reminder=True,
        all_pending_labels=lambda: ["SSN / Seguro Social"],
    )
    with (
        patch(
            "app.services.onboarding_reminders.fetch_clients_with_active_portal_user",
            return_value=[(client, portal_user)],
        ),
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
    mock_notify.return_value.notify.assert_called_once()


def test_run_onboarding_reminders_skips_clients_without_active_portal_user(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")

    with patch(
        "app.services.onboarding_reminders.fetch_clients_with_active_portal_user",
        return_value=[],
    ):
        summary = run_onboarding_reminders(db_session)

    assert summary == {
        "processed": 0,
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": True,
    }
    db_session.commit.assert_called_once()


def test_run_onboarding_reminders_skips_within_cooldown(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    client = _sample_client(
        last_onboarding_reminder_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    gaps = MagicMock(
        needs_reminder=True,
        all_pending_labels=lambda: ["SSN / Seguro Social"],
    )
    settings = MagicMock()
    settings.portal_login_url = "https://portal.example/login"
    settings.notifications_dry_run = True
    settings.onboarding_reminder_cooldown_hours = 720

    with (
        patch("app.services.onboarding_reminders.get_settings", return_value=settings),
        patch(
            "app.services.onboarding_reminders.fetch_clients_with_active_portal_user",
            return_value=[(client, _sample_portal_user(client))],
        ),
        patch("app.services.onboarding_reminders.analyze_onboarding_gaps", return_value=gaps),
        patch("app.services.onboarding_reminders.send_onboarding_reminder_email") as send_email,
        patch("app.services.onboarding_reminders.send_onboarding_reminder_whatsapp", return_value=False),
    ):
        summary = run_onboarding_reminders(db_session)

    send_email.assert_not_called()
    assert summary["processed"] == 1
    assert summary["sent"] == 0
    assert summary["skipped"] == 1


def test_run_onboarding_reminders_skips_recently_approved_without_prior_send(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    client = _sample_client(
        last_onboarding_reminder_at=None,
        approved_at=recent,
        created_at=recent,
    )
    gaps = MagicMock(
        needs_reminder=True,
        all_pending_labels=lambda: ["SSN / Seguro Social"],
    )
    settings = MagicMock()
    settings.portal_login_url = "https://portal.example/login"
    settings.notifications_dry_run = True
    settings.onboarding_reminder_cooldown_hours = 2160

    with (
        patch("app.services.onboarding_reminders.get_settings", return_value=settings),
        patch(
            "app.services.onboarding_reminders.fetch_clients_with_active_portal_user",
            return_value=[(client, _sample_portal_user(client))],
        ),
        patch("app.services.onboarding_reminders.analyze_onboarding_gaps", return_value=gaps),
        patch("app.services.onboarding_reminders.send_onboarding_reminder_email") as send_email,
        patch("app.services.onboarding_reminders.send_onboarding_reminder_whatsapp", return_value=False),
    ):
        summary = run_onboarding_reminders(db_session)

    send_email.assert_not_called()
    assert summary["skipped"] == 1


def test_run_onboarding_reminders_sends_after_cooldown(db_session, monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")
    client = _sample_client(
        last_onboarding_reminder_at=datetime.now(timezone.utc) - timedelta(hours=800),
    )
    portal_user = _sample_portal_user(client)
    gaps = MagicMock(
        needs_reminder=True,
        all_pending_labels=lambda: ["SSN / Seguro Social"],
    )
    settings = MagicMock()
    settings.portal_login_url = "https://portal.example/login"
    settings.notifications_dry_run = True
    settings.onboarding_reminder_cooldown_hours = 720

    with (
        patch("app.services.onboarding_reminders.get_settings", return_value=settings),
        patch(
            "app.services.onboarding_reminders.fetch_clients_with_active_portal_user",
            return_value=[(client, portal_user)],
        ),
        patch("app.services.onboarding_reminders.analyze_onboarding_gaps", return_value=gaps),
        patch("app.services.onboarding_reminders.send_onboarding_reminder_email", return_value=True),
        patch("app.services.onboarding_reminders.send_onboarding_reminder_whatsapp", return_value=False),
        patch("app.services.onboarding_reminders.NotificationService"),
    ):
        summary = run_onboarding_reminders(db_session)

    assert summary["processed"] == 1
    assert summary["sent"] == 1
    assert summary["skipped"] == 0
    assert client.last_onboarding_reminder_at is not None


def test_scheduler_starts_when_onboarding_interval_zero():
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        jwt_secret_key="test-secret-key-for-unit-tests-only-32chars",
        onboarding_reminder_interval_minutes=0,
    )
    stop_event = start_onboarding_reminder_scheduler(settings)
    assert stop_event is not None
    from app.workers.inline_scheduler import stop_onboarding_reminder_scheduler

    stop_onboarding_reminder_scheduler()


def test_scheduler_starts_when_interval_positive():
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        jwt_secret_key="test-secret-key-for-unit-tests-only-32chars",
        onboarding_reminder_interval_minutes=5,
    )
    stop_event = start_onboarding_reminder_scheduler(settings)
    assert stop_event is not None
    duplicate = start_onboarding_reminder_scheduler(settings)
    assert duplicate is stop_event
    from app.workers.inline_scheduler import stop_onboarding_reminder_scheduler

    stop_onboarding_reminder_scheduler()
