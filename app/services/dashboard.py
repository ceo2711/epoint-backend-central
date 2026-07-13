from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models.enums import ClientStatus
from app.models.merchant import Merchant
from app.models.user import User
from app.services.clients import ClientService

SALES_STATUSES = (
    ClientStatus.PENDIENTE_DE_REVISION.value,
    ClientStatus.RECHAZADO.value,
    ClientStatus.APROBADO_PARA_ONBOARDING.value,
)

SALES_CONVERTED_STATUSES = (
    ClientStatus.APROBADO_PARA_ONBOARDING.value,
    ClientStatus.EN_CARGA_DATOS.value,
    ClientStatus.DOCUMENTOS_EN_REVISION.value,
    ClientStatus.LISTO_PARA_TABLERO.value,
    ClientStatus.ONBOARDING_EN_PROGRESO.value,
    ClientStatus.ONBOARDING_COMPLETADO.value,
)

ONBOARDING_STATUSES = (
    ClientStatus.APROBADO_PARA_ONBOARDING.value,
    ClientStatus.EN_CARGA_DATOS.value,
    ClientStatus.DOCUMENTOS_EN_REVISION.value,
    ClientStatus.LISTO_PARA_TABLERO.value,
    ClientStatus.ONBOARDING_EN_PROGRESO.value,
    ClientStatus.ONBOARDING_COMPLETADO.value,
)

AREA_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("VENTAS", "Ventas", SALES_STATUSES),
    ("ONBOARDING", "Onboarding", ONBOARDING_STATUSES),
)

TIMESERIES_DAYS = 30
PROJECTION_DAYS = 14


def _area_definitions_for_role(role_code: str) -> list[tuple[str, str, tuple[str, ...], str]]:
    """Áreas visibles y alcance según rol."""
    if role_code == "SALES_REP":
        return [("VENTAS", "Mis ventas", SALES_STATUSES, "personal")]
    if role_code == "ONBOARDING_MANAGER":
        return [("ONBOARDING", "Onboarding", ONBOARDING_STATUSES, "general")]
    return [
        ("VENTAS", "Ventas", SALES_STATUSES, "general"),
        ("ONBOARDING", "Onboarding", ONBOARDING_STATUSES, "general"),
    ]


def _viewer_scope_for_role(role_code: str) -> str:
    return "personal" if role_code == "SALES_REP" else "general"


def _fill_timeseries(start: date, days: int, counts_by_date: dict[str, int]) -> list[dict[str, int | str]]:
    points: list[dict[str, int | str]] = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        key = current.isoformat()
        points.append({"date": key, "count": counts_by_date.get(key, 0)})
    return points


def _build_projections(history: list[dict[str, int | str]], start: date, days: int) -> list[dict[str, float | str]]:
    total = sum(int(point["count"]) for point in history)
    average = total / len(history) if history else 0.0
    projections: list[dict[str, float | str]] = []
    for offset in range(1, days + 1):
        current = start + timedelta(days=offset)
        projections.append({"date": current.isoformat(), "projected": round(average, 2)})
    return projections


class DashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.clients = ClientService(db)

    def get_metrics(self, user: User, *, merchant_id: int | None = None) -> dict:
        if merchant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seleccioná un comercio activo para ver las métricas",
            )

        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comercio no encontrado")

        scoped = self.clients._scoped_clients_query(user, merchant_id).subquery()

        status_rows = self.db.execute(
            select(scoped.c.status, func.count()).group_by(scoped.c.status)
        ).all()
        by_status: dict[str, int] = {status: count for status, count in status_rows}
        for status in ClientStatus:
            by_status.setdefault(status.value, 0)

        summary = self.clients.get_client_stats(user, merchant_id=merchant_id)
        role_code = user.role.code
        areas = [
            self._build_area_metrics(code, name, statuses, by_status, scope)
            for code, name, statuses, scope in _area_definitions_for_role(role_code)
        ]

        today = date.today()
        series_start = today - timedelta(days=TIMESERIES_DAYS - 1)

        registration_rows = self.db.execute(
            select(cast(scoped.c.created_at, Date).label("day"), func.count())
            .where(cast(scoped.c.created_at, Date) >= series_start)
            .group_by("day")
            .order_by("day")
        ).all()
        registrations_by_date = {row.day.isoformat(): row[1] for row in registration_rows}
        registrations = _fill_timeseries(series_start, TIMESERIES_DAYS, registrations_by_date)

        completion_rows = self.db.execute(
            select(cast(scoped.c.updated_at, Date).label("day"), func.count())
            .where(
                scoped.c.status == ClientStatus.ONBOARDING_COMPLETADO.value,
                cast(scoped.c.updated_at, Date) >= series_start,
            )
            .group_by("day")
            .order_by("day")
        ).all()
        completions_by_date = {row.day.isoformat(): row[1] for row in completion_rows}
        completions = _fill_timeseries(series_start, TIMESERIES_DAYS, completions_by_date)

        return {
            "merchant": {
                "id": merchant.id,
                "code": merchant.code,
                "name": merchant.name,
            },
            "viewer_scope": _viewer_scope_for_role(role_code),
            "summary": summary,
            "by_status": by_status,
            "areas": areas,
            "registrations": registrations,
            "completions": completions,
            "registration_projections": _build_projections(registrations, today, PROJECTION_DAYS),
            "completion_projections": _build_projections(completions, today, PROJECTION_DAYS),
        }

    def _build_area_metrics(
        self,
        code: str,
        name: str,
        statuses: tuple[str, ...],
        by_status: dict[str, int],
        scope: str = "general",
    ) -> dict:
        if code == "VENTAS":
            return self._build_sales_area_metrics(name, by_status, scope)

        status_counts = [{"status": status, "count": by_status.get(status, 0)} for status in statuses]
        total = sum(item["count"] for item in status_counts)
        completed = by_status.get(ClientStatus.ONBOARDING_COMPLETADO.value, 0)
        in_pipeline = total - completed

        return {
            "code": code,
            "name": name,
            "scope": scope,
            "total": total,
            "in_pipeline": in_pipeline,
            "completed": completed,
            "conversion_rate": None,
            "by_status": status_counts,
        }

    def _build_sales_area_metrics(
        self,
        name: str,
        by_status: dict[str, int],
        scope: str,
    ) -> dict:
        pending = by_status.get(ClientStatus.PENDIENTE_DE_REVISION.value, 0)
        rejected = by_status.get(ClientStatus.RECHAZADO.value, 0)
        converted = sum(by_status.get(status, 0) for status in SALES_CONVERTED_STATUSES)
        inactive = by_status.get(ClientStatus.INACTIVO.value, 0)
        total = pending + rejected + converted + inactive

        status_counts = [
            {"status": ClientStatus.PENDIENTE_DE_REVISION.value, "count": pending},
            {"status": ClientStatus.RECHAZADO.value, "count": rejected},
            {
                "status": ClientStatus.APROBADO_PARA_ONBOARDING.value,
                "count": converted,
            },
        ]

        denominator = pending + rejected + converted
        conversion_rate: float | None = None
        if denominator > 0:
            conversion_rate = round((converted / denominator) * 100, 1)

        return {
            "code": "VENTAS",
            "name": name,
            "scope": scope,
            "total": total,
            "in_pipeline": pending,
            "completed": 0,
            "conversion_rate": conversion_rate,
            "by_status": status_counts,
        }
