from unittest.mock import MagicMock

import pytest

from app.services.clients import ClientService


def _user(role_code: str, user_id: int = 1) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role.code = role_code
    return user


class TestUserCanViewClientOnboardingData:
    @pytest.mark.parametrize(
        "role_code,expected",
        [
            ("ADMIN", True),
            ("ONBOARDING_MANAGER", True),
            ("SALES_REP", False),
            ("AREA_LEADER", False),
        ],
    )
    def test_staff_roles_without_assignment(self, role_code: str, expected: bool):
        db = MagicMock()
        service = ClientService(db)
        assert service.user_can_view_client_onboarding_data(_user(role_code), 99) is expected

    def test_advisor_requires_active_assignment(self):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        service = ClientService(db)
        assert service.user_can_view_client_onboarding_data(_user("ADVISOR"), 99) is False

    def test_advisor_with_assignment(self):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = 1
        service = ClientService(db)
        assert service.user_can_view_client_onboarding_data(_user("ADVISOR"), 99) is True


class TestUserCanViewApprovedClientWorkspace:
    def _client(self, approved_at=None):
        client = MagicMock()
        client.id = 99
        client.approved_at = approved_at
        return client

    def test_denies_unapproved_client(self):
        db = MagicMock()
        db.get.return_value = self._client(approved_at=None)
        service = ClientService(db)
        assert service.user_can_view_approved_client_workspace(_user("ONBOARDING_MANAGER"), 99) is False

    def test_allows_approved_client_for_onboarding(self):
        db = MagicMock()
        client = self._client(approved_at="2026-07-05T00:00:00Z")
        db.get.return_value = client
        service = ClientService(db)
        assert (
            service.user_can_view_approved_client_workspace(
                _user("ONBOARDING_MANAGER"), 99, client=client
            )
            is True
        )
