from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_config_requires_auth(client):
    response = client.get("/api/v1/onboarding-reminders/config")
    assert response.status_code == 401


def test_config_returns_interval(client, monkeypatch):
    monkeypatch.setenv("ONBOARDING_REMINDER_INTERVAL_MINUTES", "15")
    monkeypatch.setenv("NOTIFICATIONS_DRY_RUN", "true")

    admin = MagicMock()
    admin.role.code = "ADMIN"

    with patch("app.api.v1.onboarding_reminders.require_onboarding_reminder_staff", return_value=admin):
        from app.api.v1.onboarding_reminders import get_onboarding_reminders_config

        result = get_onboarding_reminders_config(current_user=admin)
        assert result.interval_minutes == 15
        assert result.automatic_enabled is True
        assert result.dry_run is True


def test_run_endpoint_delegates_to_service(client):
    admin = MagicMock()
    admin.role.code = "ONBOARDING_MANAGER"
    mock_db = MagicMock()
    service_result = {
        "processed": 2,
        "sent": 1,
        "skipped": 1,
        "failed": 0,
        "dry_run": False,
    }

    with (
        patch("app.api.v1.onboarding_reminders.require_onboarding_reminder_staff", return_value=admin),
        patch("app.api.v1.onboarding_reminders.run_onboarding_reminders", return_value=service_result) as mock_run,
    ):
        from app.api.v1.onboarding_reminders import run_onboarding_reminders_now

        response = run_onboarding_reminders_now(db=mock_db, current_user=admin)

    mock_run.assert_called_once_with(mock_db)
    assert response.processed == 2
    assert response.sent == 1
    assert response.dry_run is False
