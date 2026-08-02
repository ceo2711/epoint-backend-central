import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.dashboard import (
    DashboardService,
    PARENT_OVERRIDE_COMMISSION_PER_SALE_USD,
    SALES_COMMISSION_PER_SALE_USD,
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
    def test_sales_uses_prospect_statuses(self):
        service = DashboardService.__new__(DashboardService)
        service.db = MagicMock()
        prospects_by_status = {
            "PENDIENTE_CONTACTAR": 5,
            "LEAD_CONTACTADO": 1,
            "CONTRATO_ENVIADO": 1,
            "PAGO_COMPLETADO": 2,
            "LEAD_CERRADO": 1,
        }
        with patch(
            "app.services.dashboard._catalog_source_codes",
            return_value=("WHATSAPP", "REFERRAL", "WEB_PAGE", "OTHER"),
        ):
            metrics = service._build_area_metrics(
                "VENTAS",
                "Ventas",
                SALES_STATUSES,
                clients_by_status={},
                prospects_by_status=prospects_by_status,
                prospects_by_source={"WHATSAPP": 3, "REFERRAL": 2},
                prospects_by_influencer=[
                    {
                        "influencer_id": 1,
                        "name": "Ana",
                        "handle": "ana",
                        "count": 4,
                        "converted_count": 1,
                    }
                ],
            )
        assert metrics["total"] == 10
        assert metrics["in_pipeline"] == 7  # pendiente + contactado + contrato
        assert metrics["completed"] == 2
        assert metrics["conversion_rate"] == 20.0  # 2 / (7+2+1)
        assert [item["status"] for item in metrics["by_status"]] == list(SALES_STATUSES)
        assert metrics["by_status"][0]["status"] == "PENDIENTE_CONTACTAR"
        assert metrics["by_status"][0]["count"] == 5
        by_source_map = {item["source"]: item["count"] for item in metrics["by_source"]}
        assert by_source_map["WHATSAPP"] == 3
        assert by_source_map["REFERRAL"] == 2
        assert by_source_map["WEB_PAGE"] == 0
        assert metrics["by_influencer"][0]["name"] == "Ana"
        assert metrics["by_influencer"][0]["count"] == 4
        assert metrics["by_influencer"][0]["converted_count"] == 1

    def test_sales_personal_scope_keeps_all_prospect_statuses(self):
        service = DashboardService.__new__(DashboardService)
        service.db = MagicMock()
        prospects_by_status = {
            "PENDIENTE_CONTACTAR": 8,
            "EN_CARGA_DATOS": 99,  # estado de cliente, debe ignorarse
            "PAGO_COMPLETADO": 1,
        }
        with patch(
            "app.services.dashboard._catalog_source_codes",
            return_value=("WHATSAPP", "REFERRAL", "WEB_PAGE", "OTHER"),
        ):
            metrics = service._build_area_metrics(
                "VENTAS",
                "Mis ventas",
                SALES_STATUSES,
                clients_by_status={"PENDIENTE_DE_REVISION": 5},
                prospects_by_status=prospects_by_status,
                scope="personal",
            )
        assert metrics["total"] == 9
        assert metrics["scope"] == "personal"
        assert metrics["completed"] == 1
        by_status_map = {item["status"]: item["count"] for item in metrics["by_status"]}
        assert "PENDIENTE_DE_REVISION" not in by_status_map
        assert by_status_map["PENDIENTE_CONTACTAR"] == 8
        assert by_status_map["PAGO_COMPLETADO"] == 1
        assert len(metrics["by_status"]) == len(SALES_STATUSES)
        assert metrics["by_influencer"] == []

    def test_onboarding_pipeline_excludes_completed(self):
        service = DashboardService.__new__(DashboardService)
        clients_by_status = {
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
            clients_by_status=clients_by_status,
            prospects_by_status={},
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
        assert areas[0][2][0] == "PENDIENTE_CONTACTAR"

    def test_onboarding_manager_only_sees_general_onboarding(self):
        areas = _area_definitions_for_role("AREA_LEADER", area_code="ONBOARDING")
        assert len(areas) == 1
        assert areas[0][0] == "ONBOARDING"
        assert areas[0][3] == "general"

    def test_admin_sees_both_areas(self):
        areas = _area_definitions_for_role("ADMIN")
        assert [area[0] for area in areas] == ["VENTAS", "ONBOARDING"]
        assert _viewer_scope_for_role("ADMIN") == "general"

    def test_sales_area_leader_only_sees_general_sales(self):
        areas = _area_definitions_for_role("AREA_LEADER", area_code="VENTAS")
        assert len(areas) == 1
        assert areas[0][0] == "VENTAS"
        assert areas[0][3] == "general"

    def test_onboarding_area_leader_only_sees_onboarding(self):
        areas = _area_definitions_for_role("AREA_LEADER", area_code="ONBOARDING")
        assert len(areas) == 1
        assert areas[0][0] == "ONBOARDING"


class TestSalesMonthlyCommission:
    def test_commission_is_fixed_amount_per_paid_sale(self):
        service = DashboardService.__new__(DashboardService)
        db = MagicMock()
        today = date.today()
        db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[(today, Decimal("1000.00"), 3)])),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        service.db = db

        result = service._sales_monthly_commission(user_id=7, merchant_id=1)

        expected = float((Decimal(3) * SALES_COMMISSION_PER_SALE_USD).quantize(Decimal("0.01")))
        assert result["monthly_paid_total"] == 1000.0
        assert result["monthly_commission"] == expected
        assert result["commission_per_sale"] == float(SALES_COMMISSION_PER_SALE_USD)
        assert result["monthly_paid_count"] == 3
        assert result["override_paid_count"] == 0
        assert result["override_commission"] == 0.0
        last_day = calendar.monthrange(today.year, today.month)[1]
        today_point = next(p for p in result["commission_series"] if p["date"] == today.isoformat())
        assert today_point["cumulative_commission"] == expected
        assert today_point["daily_commission"] == expected
        assert len(result["commission_series"]) == last_day
        assert result["commission_series"][0]["date"] == date(today.year, today.month, 1).isoformat()
        assert result["commission_series"][-1]["date"] == date(
            today.year, today.month, last_day
        ).isoformat()
        assert result["commission_series"][-1]["cumulative_commission"] == expected
        if today.day < last_day:
            assert result["commission_series"][-1]["daily_commission"] == 0.0
        else:
            assert result["commission_series"][-1]["daily_commission"] == expected

    def test_parent_receives_override_for_sub_seller_sales(self):
        service = DashboardService.__new__(DashboardService)
        db = MagicMock()
        today = date.today()
        db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[(today, Decimal("400.00"), 1)])),
            MagicMock(
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[11, 12])))
            ),
            MagicMock(all=MagicMock(return_value=[(today, Decimal("900.00"), 2)])),
        ]
        service.db = db

        result = service._sales_monthly_commission(user_id=7, merchant_id=1)

        assert result["monthly_paid_count"] == 1
        assert result["override_paid_count"] == 2
        assert result["own_commission"] == float(SALES_COMMISSION_PER_SALE_USD)
        assert result["override_commission"] == float(
            Decimal(2) * PARENT_OVERRIDE_COMMISSION_PER_SALE_USD
        )
        assert result["monthly_commission"] == 1000.0

    def test_sales_area_includes_commission_when_provided(self):
        service = DashboardService.__new__(DashboardService)
        service.db = MagicMock()
        with patch(
            "app.services.dashboard._catalog_source_codes",
            return_value=("WHATSAPP", "OTHER"),
        ):
            metrics = service._build_sales_area_metrics(
                "Mis ventas",
                {"PENDIENTE_CONTACTAR": 1, "PAGO_COMPLETADO": 0},
                {},
                "personal",
                sales_commission={
                    "monthly_paid_total": 200.0,
                    "monthly_commission": 500.0,
                    "commission_per_sale": 500.0,
                    "monthly_paid_count": 1,
                    "commission_series": [
                        {
                            "date": "2026-07-01",
                            "daily_paid": 200.0,
                            "daily_commission": 500.0,
                            "cumulative_commission": 500.0,
                        }
                    ],
                },
            )
        assert metrics["monthly_commission"] == 500.0
        assert metrics["commission_per_sale"] == 500.0
        assert metrics["monthly_paid_total"] == 200.0
        assert metrics["scope"] == "personal"
        assert len(metrics["commission_series"]) == 1


class TestSalesTeamLeadership:
    def test_sales_team_leadership_picks_best_weekday(self):
        service = DashboardService.__new__(DashboardService)
        db = MagicMock()
        today = date.today()
        mondays: list[date] = []
        wednesdays: list[date] = []
        cursor = date(today.year, today.month, 1)
        while cursor.month == today.month:
            if cursor.weekday() == 0:
                mondays.append(cursor)
            if cursor.weekday() == 2:
                wednesdays.append(cursor)
            cursor += timedelta(days=1)
        monday = mondays[0]
        wednesday = wednesdays[0]
        monday_dt = datetime(monday.year, monday.month, monday.day, 15, tzinfo=timezone.utc)
        wednesday_dt = datetime(wednesday.year, wednesday.month, wednesday.day, 15, tzinfo=timezone.utc)

        rep = SimpleNamespace(id=10, first_name="Ana", last_name="Ventas", sede_id=1)
        db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[rep])))),
            MagicMock(
                all=MagicMock(
                    return_value=[
                        (monday_dt, Decimal("100"), 10),
                        (wednesday_dt, Decimal("200"), 10),
                        (wednesday_dt, Decimal("50"), 10),
                    ]
                )
            ),
        ]
        service.db = db
        actor = SimpleNamespace(
            role=SimpleNamespace(code="AREA_LEADER"),
            sede_id=1,
            area=SimpleNamespace(code="VENTAS"),
        )

        with patch("app.services.dashboard.effective_sede_id", return_value=1):
            result = service._sales_team_leadership_metrics(actor=actor, merchant_id=1)

        assert result["best_weekday"] == 2
        assert result["best_weekday_paid_count"] == 2
        assert result["team_monthly_paid_count"] == 3
        assert result["team_monthly_commission"] == 1500.0
        assert result["active_sales_reps"] == 1
