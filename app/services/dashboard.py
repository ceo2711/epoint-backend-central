from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models.enums import ClientSource, ClientStatus, ProspectStatus
from app.models.merchant import Merchant
from app.models.payment_link import PaymentLink, PaymentLinkStatus
from app.models.user import User
from app.services.clients import ClientService
from app.services.prospects import ProspectService

# Comisión provisional del vendedor sobre pagos de prospectos.
SALES_COMMISSION_RATE = Decimal("0.15")

# Embudo comercial = estados de prospecto (antes de pasar a cliente).
SALES_STATUSES = (
    ProspectStatus.PENDIENTE_CONTACTAR.value,
    ProspectStatus.LEAD_CONTACTADO.value,
    ProspectStatus.LEAD_CERRADO.value,
    ProspectStatus.CONTRATO_ENVIADO.value,
    ProspectStatus.PAGO_COMPLETADO.value,
)

SALES_PIPELINE_STATUSES = (
    ProspectStatus.PENDIENTE_CONTACTAR.value,
    ProspectStatus.LEAD_CONTACTADO.value,
    ProspectStatus.CONTRATO_ENVIADO.value,
)

SALES_SOURCES = tuple(source.value for source in ClientSource)

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
        self.prospects = ProspectService(db)

    def get_metrics(
        self,
        user: User,
        *,
        merchant_id: int | None = None,
        filter_sede_id: int | None = None,
    ) -> dict:
        if merchant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seleccioná un comercio activo para ver las métricas",
            )

        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comercio no encontrado")

        use_sede_scope = filter_sede_id is not None
        scope_merchant_id = None if use_sede_scope else merchant_id
        scope_all_merchants = use_sede_scope

        scoped_clients = self.clients._scoped_clients_query(
            user,
            scope_merchant_id,
            all_merchants=scope_all_merchants,
            filter_sede_id=filter_sede_id,
        ).subquery()
        scoped_prospects = self.prospects._scoped_query(
            user,
            scope_merchant_id,
            all_merchants=scope_all_merchants,
            filter_sede_id=filter_sede_id,
        ).subquery()

        client_status_rows = self.db.execute(
            select(scoped_clients.c.status, func.count()).group_by(scoped_clients.c.status)
        ).all()
        clients_by_status: dict[str, int] = {status: count for status, count in client_status_rows}
        for status in ClientStatus:
            clients_by_status.setdefault(status.value, 0)

        prospect_status_rows = self.db.execute(
            select(scoped_prospects.c.status, func.count()).group_by(scoped_prospects.c.status)
        ).all()
        prospects_by_status: dict[str, int] = {
            status: count for status, count in prospect_status_rows
        }
        for status in ProspectStatus:
            prospects_by_status.setdefault(status.value, 0)

        prospect_source_rows = self.db.execute(
            select(scoped_prospects.c.source, func.count()).group_by(scoped_prospects.c.source)
        ).all()
        prospects_by_source: dict[str, int] = {}
        for source, count in prospect_source_rows:
            key = source or ClientSource.OTHER.value
            prospects_by_source[key] = prospects_by_source.get(key, 0) + count
        for source in ClientSource:
            prospects_by_source.setdefault(source.value, 0)

        summary = self.clients.get_client_stats(
            user,
            merchant_id=scope_merchant_id,
            all_merchants=scope_all_merchants,
            filter_sede_id=filter_sede_id,
        )
        role_code = user.role.code
        sales_commission = None
        if role_code == "SALES_REP":
            sales_commission = self._sales_monthly_commission(
                user_id=user.id,
                merchant_id=merchant_id,
            )

        areas = [
            self._build_area_metrics(
                code,
                name,
                statuses,
                clients_by_status=clients_by_status,
                prospects_by_status=prospects_by_status,
                prospects_by_source=prospects_by_source,
                scope=scope,
                sales_commission=sales_commission if code == "VENTAS" and scope == "personal" else None,
            )
            for code, name, statuses, scope in _area_definitions_for_role(role_code)
        ]

        today = date.today()
        series_start = today - timedelta(days=TIMESERIES_DAYS - 1)

        client_registration_rows = self.db.execute(
            select(cast(scoped_clients.c.created_at, Date).label("day"), func.count())
            .where(cast(scoped_clients.c.created_at, Date) >= series_start)
            .group_by("day")
            .order_by("day")
        ).all()
        client_registrations_by_date = {
            row.day.isoformat(): row[1] for row in client_registration_rows
        }
        registrations = _fill_timeseries(series_start, TIMESERIES_DAYS, client_registrations_by_date)

        prospect_registration_rows = self.db.execute(
            select(cast(scoped_prospects.c.created_at, Date).label("day"), func.count())
            .where(cast(scoped_prospects.c.created_at, Date) >= series_start)
            .group_by("day")
            .order_by("day")
        ).all()
        prospect_registrations_by_date = {
            row.day.isoformat(): row[1] for row in prospect_registration_rows
        }
        prospect_registrations = _fill_timeseries(
            series_start, TIMESERIES_DAYS, prospect_registrations_by_date
        )

        completion_rows = self.db.execute(
            select(cast(scoped_clients.c.updated_at, Date).label("day"), func.count())
            .where(
                scoped_clients.c.status == ClientStatus.ONBOARDING_COMPLETADO.value,
                cast(scoped_clients.c.updated_at, Date) >= series_start,
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
            "by_status": clients_by_status,
            "areas": areas,
            "registrations": registrations,
            "prospect_registrations": prospect_registrations,
            "completions": completions,
            "registration_projections": _build_projections(registrations, today, PROJECTION_DAYS),
            "prospect_registration_projections": _build_projections(
                prospect_registrations, today, PROJECTION_DAYS
            ),
            "completion_projections": _build_projections(completions, today, PROJECTION_DAYS),
        }

    def _sales_monthly_commission(self, *, user_id: int, merchant_id: int) -> dict:
        """Serie diaria del mes + comisión acumulada del vendedor (15% sobre cobrado)."""
        today = date.today()
        month_start = date(today.year, today.month, 1)
        month_start_dt = datetime(today.year, today.month, 1, tzinfo=timezone.utc)

        day_col = cast(PaymentLink.paid_at, Date).label("day")
        rows = self.db.execute(
            select(
                day_col,
                func.coalesce(func.sum(PaymentLink.amount), 0),
                func.count(PaymentLink.id),
            )
            .where(
                PaymentLink.status == PaymentLinkStatus.PAID.value,
                PaymentLink.paid_at.is_not(None),
                PaymentLink.paid_at >= month_start_dt,
                PaymentLink.created_by_user_id == user_id,
                PaymentLink.merchant_id == merchant_id,
                PaymentLink.prospect_id.is_not(None),
            )
            .group_by(day_col)
            .order_by(day_col)
        ).all()

        by_day: dict[date, tuple[Decimal, int]] = {}
        for row in rows:
            day_value = row[0]
            if isinstance(day_value, datetime):
                day_value = day_value.date()
            by_day[day_value] = (Decimal(str(row[1])), int(row[2]))

        series: list[dict] = []
        running_paid = Decimal("0")
        paid_count = 0
        current = month_start
        while current <= today:
            day_paid, day_count = by_day.get(current, (Decimal("0"), 0))
            running_paid += day_paid
            paid_count += day_count
            daily_commission = (day_paid * SALES_COMMISSION_RATE).quantize(Decimal("0.01"))
            cumulative = (running_paid * SALES_COMMISSION_RATE).quantize(Decimal("0.01"))
            series.append(
                {
                    "date": current.isoformat(),
                    "daily_paid": float(day_paid),
                    "daily_commission": float(daily_commission),
                    "cumulative_commission": float(cumulative),
                }
            )
            current += timedelta(days=1)

        monthly_commission = (running_paid * SALES_COMMISSION_RATE).quantize(Decimal("0.01"))
        return {
            "monthly_paid_total": float(running_paid),
            "monthly_commission": float(monthly_commission),
            "commission_rate": float(SALES_COMMISSION_RATE),
            "monthly_paid_count": paid_count,
            "commission_series": series,
        }

    def _build_area_metrics(
        self,
        code: str,
        name: str,
        statuses: tuple[str, ...],
        *,
        clients_by_status: dict[str, int],
        prospects_by_status: dict[str, int],
        prospects_by_source: dict[str, int] | None = None,
        scope: str = "general",
        sales_commission: dict | None = None,
    ) -> dict:
        if code == "VENTAS":
            return self._build_sales_area_metrics(
                name,
                prospects_by_status,
                prospects_by_source or {},
                scope,
                sales_commission=sales_commission,
            )

        status_counts = [
            {"status": status, "count": clients_by_status.get(status, 0)} for status in statuses
        ]
        total = sum(item["count"] for item in status_counts)
        completed = clients_by_status.get(ClientStatus.ONBOARDING_COMPLETADO.value, 0)
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
            "by_source": [],
        }

    def _build_sales_area_metrics(
        self,
        name: str,
        by_status: dict[str, int],
        by_source: dict[str, int],
        scope: str,
        *,
        sales_commission: dict | None = None,
    ) -> dict:
        status_counts = [
            {"status": status, "count": by_status.get(status, 0)} for status in SALES_STATUSES
        ]
        total = sum(item["count"] for item in status_counts)
        in_pipeline = sum(by_status.get(status, 0) for status in SALES_PIPELINE_STATUSES)
        completed = by_status.get(ProspectStatus.PAGO_COMPLETADO.value, 0)
        closed = by_status.get(ProspectStatus.LEAD_CERRADO.value, 0)

        denominator = in_pipeline + completed + closed
        conversion_rate: float | None = None
        if denominator > 0:
            conversion_rate = round((completed / denominator) * 100, 1)

        source_counts = [
            {"source": source, "count": by_source.get(source, 0)} for source in SALES_SOURCES
        ]

        metrics: dict = {
            "code": "VENTAS",
            "name": name,
            "scope": scope,
            "total": total,
            "in_pipeline": in_pipeline,
            "completed": completed,
            "conversion_rate": conversion_rate,
            "by_status": status_counts,
            "by_source": source_counts,
        }
        if sales_commission:
            metrics.update(sales_commission)
        return metrics
