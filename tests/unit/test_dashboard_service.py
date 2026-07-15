from datetime import date

from app.services.dashboard import (
    DashboardService,
    SALES_STATUSES,
    _area_definitions_for_role,
    _build_projections,
    _fill_timeseries,
    _viewer_scope_for_role,
)


class TestDashboardHelpers:
    def test_fill_timeseries_fills_missing_days(self):
        start = date(2026, 1, 1)
        points = _fill_timeseries(start, 3, {"2026-01-02": 4})
        assert points == [
            {"date": "2026-01-01", "count": 0},
            {"date": "2026-01-02", "count": 4},
            {"date": "2026-01-03", "count": 0},
        ]

    def test_build_projections_uses_average(self):
        history = [
            {"date": "2026-01-01", "count": 2},
            {"date": "2026-01-02", "count": 4},
        ]
        projections = _build_projections(history, date(2026, 1, 2), 2)
        assert projections[0]["projected"] == 3.0
        assert projections[1]["projected"] == 3.0


class TestDashboardAreaMetrics:
    def test_sales_conversion_rate(self):
        service = DashboardService.__new__(DashboardService)
        by_status = {
            "PENDIENTE_DE_REVISION": 2,
            "RECHAZADO": 1,
            "APROBADO_PARA_ONBOARDING": 3,
        }
        metrics = service._build_area_metrics("VENTAS", "Ventas", SALES_STATUSES, by_status)
        assert metrics["total"] == 6
        assert metrics["in_pipeline"] == 2
        assert metrics["conversion_rate"] == 50.0

    def test_sales_counts_entering_data_as_converted(self):
        service = DashboardService.__new__(DashboardService)
        by_status = {
            "PENDIENTE_DE_REVISION": 8,
            "RECHAZADO": 0,
            "EN_CARGA_DATOS": 2,
        }
        metrics = service._build_area_metrics("VENTAS", "Mis ventas", SALES_STATUSES, by_status, scope="personal")
        assert metrics["total"] == 10
        assert metrics["in_pipeline"] == 8
        assert metrics["conversion_rate"] == 20.0
        approved_bucket = next(
            item for item in metrics["by_status"] if item["status"] == "APROBADO_PARA_ONBOARDING"
        )
        assert approved_bucket["count"] == 2

    def test_onboarding_pipeline_excludes_completed(self):
        service = DashboardService.__new__(DashboardService)
        by_status = {
            "APROBADO_PARA_ONBOARDING": 2,
            "EN_CARGA_DATOS": 1,
            "ONBOARDING_COMPLETADO": 4,
        }
        metrics = service._build_area_metrics(
            "ONBOARDING",
            "Onboarding",
            (
                "APROBADO_PARA_ONBOARDING",
                "EN_CARGA_DATOS",
                "ONBOARDING_COMPLETADO",
            ),
            by_status,
        )
        assert metrics["total"] == 7
        assert metrics["in_pipeline"] == 3
        assert metrics["completed"] == 4


class TestDashboardRoleAreas:
    def test_sales_rep_only_sees_personal_sales(self):
        areas = _area_definitions_for_role("SALES_REP")
        assert len(areas) == 1
        assert areas[0][0] == "VENTAS"
        assert areas[0][3] == "personal"

    def test_onboarding_manager_only_sees_general_onboarding(self):
        areas = _area_definitions_for_role("ONBOARDING_MANAGER")
        assert len(areas) == 1
        assert areas[0][0] == "ONBOARDING"
        assert areas[0][3] == "general"

    def test_admin_sees_both_areas(self):
        areas = _area_definitions_for_role("ADMIN")
        assert len(areas) == 2
        assert [area[0] for area in areas] == ["VENTAS", "ONBOARDING"]

    def test_viewer_scope_by_role(self):
        assert _viewer_scope_for_role("SALES_REP") == "personal"
        assert _viewer_scope_for_role("ONBOARDING_MANAGER") == "general"
        assert _viewer_scope_for_role("ADMIN") == "general"
