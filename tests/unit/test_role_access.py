from types import SimpleNamespace

from app.services.role_access import (
    can_access_docusign,
    can_filter_clients_by_sales_rep,
    can_manage_onboarding,
    can_run_onboarding_reminders,
    can_supervise_sales_reps,
    is_onboarding_area_leader,
    is_sales_area_leader,
    is_sede_admin,
)


def _user(*, role: str, area: str | None = None, parent_user_id: int | None = None):
    return SimpleNamespace(
        role=SimpleNamespace(code=role),
        area=SimpleNamespace(code=area) if area else None,
        parent_user_id=parent_user_id,
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
        assert is_onboarding_area_leader(_user(role="AREA_LEADER", area="ONBOARDING"))

    def test_can_supervise_sales_reps(self):
        assert can_supervise_sales_reps(_user(role="ADMIN"))
        assert can_supervise_sales_reps(_user(role="BRANCH_MANAGER"))
        assert can_supervise_sales_reps(_user(role="AREA_LEADER", area="VENTAS"))
        assert not can_supervise_sales_reps(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_supervise_sales_reps(_user(role="SALES_REP", area="VENTAS"))

    def test_can_sell_and_own_sub_sellers(self):
        from app.services.role_access import can_be_prospect_owner, can_own_sub_sellers, can_sell

        assert can_sell(_user(role="SALES_REP", area="VENTAS"))
        assert can_sell(_user(role="SUB_SELLER", area="VENTAS"))
        assert can_sell(_user(role="AREA_LEADER", area="VENTAS"))
        assert not can_sell(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_sell(_user(role="BRANCH_MANAGER"))

        assert can_be_prospect_owner(_user(role="AREA_LEADER", area="VENTAS"))
        assert not can_be_prospect_owner(_user(role="AREA_LEADER", area="ONBOARDING"))

        assert can_own_sub_sellers(_user(role="SALES_REP", area="VENTAS"))
        assert can_own_sub_sellers(_user(role="AREA_LEADER", area="VENTAS"))
        assert not can_own_sub_sellers(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_own_sub_sellers(_user(role="SUB_SELLER", area="VENTAS"))
        assert not can_own_sub_sellers(_user(role="SALES_REP", area="VENTAS", parent_user_id=1))
    def test_can_filter_clients_by_sales_rep(self):
        assert can_filter_clients_by_sales_rep(_user(role="ADMIN"))
        assert can_filter_clients_by_sales_rep(_user(role="BRANCH_MANAGER"))
        assert can_filter_clients_by_sales_rep(_user(role="AREA_LEADER", area="VENTAS"))
        assert can_filter_clients_by_sales_rep(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_filter_clients_by_sales_rep(_user(role="ADVISOR"))
        assert can_filter_clients_by_sales_rep(_user(role="AREA_LEADER", area="ASESORES"))

    def test_can_manage_onboarding_includes_advisor(self):
        assert can_manage_onboarding(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert can_manage_onboarding(_user(role="ADVISOR"))
        assert can_manage_onboarding(_user(role="AREA_LEADER", area="ASESORES"))
        assert can_manage_onboarding(_user(role="ADMIN"))
        assert not can_manage_onboarding(_user(role="SALES_REP", area="VENTAS"))
        assert not can_manage_onboarding(_user(role="AREA_LEADER", area="VENTAS"))

    def test_advisor_cannot_run_onboarding_reminders(self):
        assert can_run_onboarding_reminders(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert can_run_onboarding_reminders(_user(role="ADMIN"))
        assert not can_run_onboarding_reminders(_user(role="ADVISOR"))

    def test_advisor_cannot_upload_client_documents(self):
        from app.services.role_access import can_download_client_documents, can_upload_client_documents

        assert can_upload_client_documents(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert can_upload_client_documents(_user(role="ADMIN"))
        assert can_upload_client_documents(_user(role="BRANCH_MANAGER"))
        assert can_upload_client_documents(_user(role="CLIENT"))
        assert not can_upload_client_documents(_user(role="ADVISOR"))

    def test_document_download_roles(self):
        from app.services.role_access import can_download_client_documents

        assert can_download_client_documents(_user(role="ADMIN"))
        assert can_download_client_documents(_user(role="BRANCH_MANAGER"))
        assert can_download_client_documents(_user(role="ADVISOR"))
        assert can_download_client_documents(_user(role="CLIENT"))
        assert not can_download_client_documents(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert not can_download_client_documents(_user(role="AREA_LEADER", area="ASESORES"))

    def test_can_access_docusign_includes_advisor(self):
        assert can_access_docusign(_user(role="ADVISOR"))
        assert can_access_docusign(_user(role="AREA_LEADER", area="ONBOARDING"))
        assert can_access_docusign(_user(role="SALES_REP", area="VENTAS"))
        assert not can_access_docusign(_user(role="CLIENT"))
