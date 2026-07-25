from types import SimpleNamespace

from app.services.role_access import (
    can_filter_clients_by_sales_rep,
    can_supervise_sales_reps,
    is_onboarding_area_leader,
    is_sales_area_leader,
    is_sede_admin,
)


def _user(*, role: str, area: str | None = None):
    return SimpleNamespace(
        role=SimpleNamespace(code=role),
        area=SimpleNamespace(code=area) if area else None,
    )


class TestRoleAccessHelpers:
    def test_sede_admin_roles(self):
        assert is_sede_admin(_user(role="ADMIN"))
        assert is_sede_admin(_user(role="BRANCH_MANAGER"))
        assert not is_sede_admin(_user(role="AREA_LEADER", area="VENTAS"))

    def test_sales_area_leader(self):
        assert is_sales_area_leader(_user(role="AREA_LEADER", area="VENTAS"))
        assert not is_sales_area_leader(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not is_sales_area_leader(_user(role="SALES_REP", area="VENTAS"))

    def test_onboarding_area_leader(self):
        assert is_onboarding_area_leader(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not is_onboarding_area_leader(_user(role="AREA_LEADER", area="VENTAS"))
        assert not is_onboarding_area_leader(_user(role="ONBOARDING_MANAGER", area="ONBOARDING"))

    def test_can_supervise_sales_reps(self):
        assert can_supervise_sales_reps(_user(role="ADMIN"))
        assert can_supervise_sales_reps(_user(role="BRANCH_MANAGER"))
        assert can_supervise_sales_reps(_user(role="AREA_LEADER", area="VENTAS"))
        assert not can_supervise_sales_reps(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_supervise_sales_reps(_user(role="SALES_REP", area="VENTAS"))

    def test_can_filter_clients_by_sales_rep(self):
        assert can_filter_clients_by_sales_rep(_user(role="ADMIN"))
        assert can_filter_clients_by_sales_rep(_user(role="BRANCH_MANAGER"))
        assert can_filter_clients_by_sales_rep(_user(role="AREA_LEADER", area="VENTAS"))
        assert can_filter_clients_by_sales_rep(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_filter_clients_by_sales_rep(_user(role="ONBOARDING_MANAGER"))
        assert not can_filter_clients_by_sales_rep(_user(role="ADVISOR"))
