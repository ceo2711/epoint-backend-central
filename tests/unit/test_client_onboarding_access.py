from unittest.mock import MagicMock, patch

import pytest

from app.services.clients import ClientService


def _user(role_code: str, user_id: int = 1, area_code: str | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role.code = role_code
    if area_code is None:
        user.area = None
    else:
        user.area = MagicMock()
        user.area.code = area_code
    return user


class TestUserCanViewClientOnboardingData:
    @pytest.mark.parametrize(
        "role_code,area_code,expected",
        [
            ("ADMIN", None, True),
            ("BRANCH_MANAGER", None, True),
                        ("AREA_LEADER", "ONBOARDING", True),
            ("AREA_LEADER", "VENTAS", False),
            ("SALES_REP", None, False),
        ],
    )
    def test_staff_roles_without_assignment(
        self, role_code: str, area_code: str | None, expected: bool
    ):
        db = MagicMock()
        service = ClientService(db)
        with patch.object(service, "user_can_access_client", return_value=True):
            assert (
                service.user_can_view_client_onboarding_data(
                    _user(role_code, area_code=area_code), 99
                )
                is expected
            )

    def test_advisor_requires_active_assignment(self):
        db = MagicMock()
        service = ClientService(db)
        with patch.object(service, "user_can_access_client", return_value=False):
            assert service.user_can_view_client_onboarding_data(_user("ADVISOR"), 99) is False

    def test_advisor_with_assignment(self):
        db = MagicMock()
        service = ClientService(db)
        with patch.object(service, "user_can_access_client", return_value=True):
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
        assert service.user_can_view_approved_client_workspace(_user("AREA_LEADER", area_code="ONBOARDING"), 99) is False

    def test_allows_approved_client_for_onboarding(self):
        db = MagicMock()
        client = self._client(approved_at="2026-07-05T00:00:00Z")
        db.get.return_value = client
        service = ClientService(db)
        with patch.object(service, "user_can_access_client", return_value=True):
            assert (
                service.user_can_view_approved_client_workspace(
                    _user("AREA_LEADER", area_code="ONBOARDING"), 99, client=client
                )
                is True
            )


class TestUserCanAccessClientMerchantScope:
    def _client_row(self, *, client_id: int = 314, merchant_id: int = 2, registered_by: int = 99):
        row = MagicMock()
        row.id = client_id
        row.merchant_id = merchant_id
        row.registered_by_user_id = registered_by
        row.sede_id = None
        return row

    def test_onboarding_manager_can_access_client_when_active_merchant_differs(self):
        db = MagicMock()
        db.execute.return_value.one_or_none.return_value = self._client_row()
        service = ClientService(db)
        user = _user("AREA_LEADER", area_code="ONBOARDING")

        with (
            patch("app.services.clients.MerchantContextService") as merchant_ctx_cls,
            patch("app.services.sede_scope.effective_sede_id", return_value=None),
        ):
            merchant_ctx_cls.return_value.user_can_access_merchant.return_value = True
            assert service.user_can_access_client(user, 314, merchant_id=1) is True
            merchant_ctx_cls.return_value.user_can_access_merchant.assert_called_once_with(user, 2)

    def test_denies_when_user_cannot_access_client_merchant(self):
        db = MagicMock()
        db.execute.return_value.one_or_none.return_value = self._client_row()
        service = ClientService(db)
        user = _user("AREA_LEADER", area_code="ONBOARDING")

        with (
            patch("app.services.clients.MerchantContextService") as merchant_ctx_cls,
            patch("app.services.sede_scope.effective_sede_id", return_value=None),
        ):
            merchant_ctx_cls.return_value.user_can_access_merchant.return_value = False
            assert service.user_can_access_client(user, 314, merchant_id=1) is False


class TestAdvisorClientScope:
    def _row(self, *, status: str):
        row = MagicMock()
        row.id = 314
        row.merchant_id = 2
        row.registered_by_user_id = 99
        row.sede_id = None
        row.status = status
        return row

    def test_denies_pending_review_even_if_assigned(self):
        db = MagicMock()
        db.execute.return_value.one_or_none.return_value = self._row(status="PENDIENTE_DE_REVISION")
        service = ClientService(db)
        with (
            patch("app.services.clients.MerchantContextService") as merchant_ctx_cls,
            patch("app.services.sede_scope.effective_sede_id", return_value=None),
        ):
            merchant_ctx_cls.return_value.user_can_access_merchant.return_value = True
            assert service.user_can_access_client(_user("ADVISOR", user_id=7), 314) is False

    def test_denies_ready_client_without_assignment(self):
        db = MagicMock()
        client_result = MagicMock()
        client_result.one_or_none.return_value = self._row(status="LISTO_PARA_TRABAJAR")
        assignment_result = MagicMock()
        assignment_result.first.return_value = None
        db.execute.side_effect = [client_result, assignment_result]
        service = ClientService(db)
        with (
            patch("app.services.clients.MerchantContextService") as merchant_ctx_cls,
            patch("app.services.sede_scope.effective_sede_id", return_value=None),
        ):
            merchant_ctx_cls.return_value.user_can_access_merchant.return_value = True
            assert service.user_can_access_client(_user("ADVISOR", user_id=7), 314) is False

    def test_allows_assigned_ready_to_work_client(self):
        db = MagicMock()
        client_result = MagicMock()
        client_result.one_or_none.return_value = self._row(status="LISTO_PARA_TRABAJAR")
        assignment_result = MagicMock()
        assignment_result.first.return_value = (11,)
        db.execute.side_effect = [client_result, assignment_result]
        service = ClientService(db)
        with (
            patch("app.services.clients.MerchantContextService") as merchant_ctx_cls,
            patch("app.services.sede_scope.effective_sede_id", return_value=None),
        ):
            merchant_ctx_cls.return_value.user_can_access_merchant.return_value = True
            assert service.user_can_access_client(_user("ADVISOR", user_id=7), 314) is True

    def test_list_query_scopes_advisor_to_assigned_ready_clients(self):
        service = ClientService(MagicMock())
        with patch("app.services.sede_scope.effective_sede_id", return_value=None):
            query = service._scoped_clients_query(_user("ADVISOR", user_id=7), None)
        sql = str(query.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "listo_para_trabajar" in sql
        assert "client_assignments" in sql

    def test_onboarding_leader_list_query_is_not_assignment_scoped(self):
        service = ClientService(MagicMock())
        with patch("app.services.sede_scope.effective_sede_id", return_value=None):
            query = service._scoped_clients_query(
                _user("AREA_LEADER", area_code="ONBOARDING"), None
            )
        sql = str(query.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "client_assignments" not in sql
