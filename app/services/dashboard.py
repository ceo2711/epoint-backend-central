import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models.enums import ClientSource, ClientStatus, ProspectStatus
from app.models.influencer import Influencer
from app.models.merchant import Merchant
from app.models.payment_link import PaymentLink, PaymentLinkStatus
from app.models.prospect import Prospect
from app.models.client import Client
from app.models.role import Role
from app.models.user import User
from app.services.clients import ClientService
from app.services.prospects import ProspectService, SALES_COMMISSION_PER_SALE_USD
from app.services.role_access import SALES_STAFF_ROLES, can_supervise_sales_reps, is_sales_area_leader, user_area_code
from app.services.sede_scope import effective_sede_id

# Embudo comercial = estados de prospecto (antes de pasar a cliente).
PARENT_OVERRIDE_COMMISSION_PER_SALE_USD = Decimal("250")
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


def _catalog_source_codes(db: Session) -> tuple[str, ...]:
    from app.services.sources import list_sources

    rows = list_sources(db, include_inactive=True)
    if rows:
        return tuple(row.code for row in rows)
    return SALES_SOURCES

ONBOARDING_STATUSES = (
    ClientStatus.APROBADO_PARA_ONBOARDING.value,
    ClientStatus.EN_CARGA_DATOS.value,
    ClientStatus.DOCUMENTOS_EN_REVISION.value,
    ClientStatus.LISTO_PARA_TRABAJAR.value,
    ClientStatus.ONBOARDING_EN_PROGRESO.value,
    ClientStatus.ONBOARDING_COMPLETADO.value,
)

AREA_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("VENTAS", "Ventas", SALES_STATUSES),
    ("ONBOARDING", "Onboarding", ONBOARDING_STATUSES),
)

TIMESERIES_DAYS = 30
PROJECTION_DAYS = 14


def _area_definitions_for_role(
    role_code: str,
    *,
    area_code: str | None = None,
) -> list[tuple[str, str, tuple[str, ...], str]]:
    """Áreas visibles y alcance según rol."""
    if role_code in SALES_STAFF_ROLES:
        return [("VENTAS", "Mis ventas", SALES_STATUSES, "personal")]
    if role_code == "AREA_LEADER" and area_code == "VENTAS":
        return [("VENTAS", "Ventas", SALES_STATUSES, "general")]
    if role_code == "ADVISOR" or (
        role_code == "AREA_LEADER" and area_code in ("ONBOARDING", "ASESORES")
    ):
        return [("ONBOARDING", "Onboarding", ONBOARDING_STATUSES, "general")]
    return [
        ("VENTAS", "Ventas", SALES_STATUSES, "general"),
        ("ONBOARDING", "Onboarding", ONBOARDING_STATUSES, "general"),
    ]


def _viewer_scope_for_role(role_code: str) -> str:
    return "personal" if role_code in SALES_STAFF_ROLES else "general"


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
        sales_rep_id: int | None = None,
    ) -> dict:
        if merchant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seleccioná un comercio activo para ver las métricas",
            )

        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comercio no encontrado")

        supervised_rep: User | None = None
        if sales_rep_id is not None:
            supervised_rep = self._resolve_supervised_sales_rep(user, sales_rep_id)

        use_sede_scope = filter_sede_id is not None
        scope_merchant_id = None if use_sede_scope else merchant_id
        scope_all_merchants = use_sede_scope

        clients_query = self.clients._scoped_clients_query(
            user,
            scope_merchant_id,
            all_merchants=scope_all_merchants,
            filter_sede_id=filter_sede_id,
        )
        prospects_query = self.prospects._scoped_query(
            user,
            scope_merchant_id,
            all_merchants=scope_all_merchants,
            filter_sede_id=filter_sede_id,
        )
        if supervised_rep is not None:
            clients_query = clients_query.where(Client.registered_by_user_id == supervised_rep.id)
            prospects_query = prospects_query.where(
                Prospect.assigned_to_user_id == supervised_rep.id
            )

        scoped_clients = clients_query.subquery()
        scoped_prospects = prospects_query.subquery()

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
        for code in _catalog_source_codes(self.db):
            prospects_by_source.setdefault(code, 0)
        for code in list(prospects_by_source):
            prospects_by_source.setdefault(code, 0)

        influencer_rows = self.db.execute(
            select(
                scoped_prospects.c.influencer_id,
                Influencer.name,
                Influencer.handle,
                func.count().label("total"),
                func.count(scoped_prospects.c.converted_client_id).label("converted"),
            )
            .select_from(scoped_prospects)
            .join(Influencer, Influencer.id == scoped_prospects.c.influencer_id)
            .where(scoped_prospects.c.influencer_id.is_not(None))
            .group_by(scoped_prospects.c.influencer_id, Influencer.name, Influencer.handle)
            .order_by(func.count().desc(), Influencer.name.asc())
        ).all()
        prospects_by_influencer = [
            {
                "influencer_id": row.influencer_id,
                "name": row.name,
                "handle": row.handle,
                "count": int(row.total),
                "converted_count": int(row.converted or 0),
            }
            for row in influencer_rows
        ]

        summary = self.clients.get_client_stats(
            user,
            merchant_id=scope_merchant_id,
            all_merchants=scope_all_merchants,
            filter_sede_id=filter_sede_id,
        )
        if supervised_rep is not None:
            approved_statuses = {
                ClientStatus.APROBADO_PARA_ONBOARDING.value,
                ClientStatus.EN_CARGA_DATOS.value,
                ClientStatus.DOCUMENTOS_EN_REVISION.value,
                ClientStatus.LISTO_PARA_TRABAJAR.value,
            }
            summary = {
                "pending_review": clients_by_status.get(ClientStatus.PENDIENTE_DE_REVISION.value, 0),
                "approved_in_onboarding": sum(
                    clients_by_status.get(s, 0) for s in approved_statuses
                ),
                "rejected": clients_by_status.get(ClientStatus.RECHAZADO.value, 0),
                "onboarding_in_progress": clients_by_status.get(
                    ClientStatus.ONBOARDING_EN_PROGRESO.value, 0
                ),
                "completed": clients_by_status.get(ClientStatus.ONBOARDING_COMPLETADO.value, 0),
                "total": sum(clients_by_status.values()),
            }

        role_code = user.role.code
        sales_commission = None
        personal_rep_id = supervised_rep.id if supervised_rep else (
            user.id if role_code in SALES_STAFF_ROLES else None
        )
        if personal_rep_id is not None:
            sales_commission = self._sales_monthly_commission(
                user_id=personal_rep_id,
                merchant_id=merchant_id,
            )

        if supervised_rep is not None:
            area_defs: list[tuple[str, str, tuple[str, ...], str]] = [
                (
                    "VENTAS",
                    f"Ventas — {supervised_rep.first_name} {supervised_rep.last_name}",
                    SALES_STATUSES,
                    "personal",
                )
            ]
            viewer_scope = "personal"
        else:
            area_defs = _area_definitions_for_role(role_code, area_code=user_area_code(user))
            viewer_scope = _viewer_scope_for_role(role_code)

        areas = [
            self._build_area_metrics(
                code,
                name,
                statuses,
                clients_by_status=clients_by_status,
                prospects_by_status=prospects_by_status,
                prospects_by_source=prospects_by_source,
                prospects_by_influencer=prospects_by_influencer,
                scope=scope,
                sales_commission=sales_commission if code == "VENTAS" and scope == "personal" else None,
            )
            for code, name, statuses, scope in area_defs
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

        sales_leadership = None
        if supervised_rep is None and is_sales_area_leader(user):
            sales_leadership = self._sales_team_leadership_metrics(
                actor=user,
                merchant_id=merchant_id,
            )
            # Adjuntar comisión de equipo al área Ventas general.
            for area in areas:
                if area["code"] == "VENTAS" and area["scope"] == "general":
                    area["monthly_paid_total"] = sales_leadership["team_monthly_paid_total"]
                    area["monthly_commission"] = sales_leadership["team_monthly_commission"]
                    area["commission_per_sale"] = sales_leadership["commission_per_sale"]
                    area["monthly_paid_count"] = sales_leadership["team_monthly_paid_count"]

        return {
            "merchant": {
                "id": merchant.id,
                "code": merchant.code,
                "name": merchant.name,
            },
            "viewer_scope": viewer_scope,
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
            "sales_leadership": sales_leadership,
        }

    def _resolve_supervised_sales_rep(self, actor: User, sales_rep_id: int) -> User:
        if not can_supervise_sales_reps(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No autorizado a ver métricas de otro vendedor",
            )
        target = self.db.execute(
            select(User)
            .join(Role)
            .where(User.id == sales_rep_id, Role.code.in_(tuple(SALES_STAFF_ROLES)))
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendedor no encontrado")
        scope = effective_sede_id(actor)
        if scope is not None and target.sede_id != scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendedor no encontrado")
        return target

    def _sales_team_leadership_metrics(self, *, actor: User, merchant_id: int) -> dict:
        """KPIs de equipo para el líder de Ventas (mes calendario actual)."""
        today = date.today()
        month_start_dt = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
        if today.month == 12:
            month_end_dt = datetime(today.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end_dt = datetime(today.year, today.month + 1, 1, tzinfo=timezone.utc)
        sede_id = effective_sede_id(actor)

        reps_query = (
            select(User)
            .join(Role)
            .where(Role.code.in_(tuple(SALES_STAFF_ROLES)), User.is_active.is_(True))
        )
        if sede_id is not None:
            reps_query = reps_query.where(User.sede_id == sede_id)
        reps = list(self.db.execute(reps_query.order_by(User.first_name, User.last_name)).scalars().all())
        rep_ids = [rep.id for rep in reps]
        rep_by_id = {rep.id: rep for rep in reps}

        weekday_counts = [0] * 7
        weekday_amounts = [Decimal("0")] * 7
        by_rep: dict[int, tuple[int, Decimal]] = {rep_id: (0, Decimal("0")) for rep_id in rep_ids}

        if rep_ids:
            rows = self.db.execute(
                select(
                    PaymentLink.paid_at,
                    PaymentLink.amount,
                    PaymentLink.created_by_user_id,
                ).where(
                    PaymentLink.status == PaymentLinkStatus.PAID.value,
                    PaymentLink.paid_at.is_not(None),
                    PaymentLink.paid_at >= month_start_dt,
                    PaymentLink.paid_at < month_end_dt,
                    PaymentLink.merchant_id == merchant_id,
                    PaymentLink.prospect_id.is_not(None),
                    PaymentLink.created_by_user_id.in_(rep_ids),
                )
            ).all()
            for paid_at, amount, creator_id in rows:
                paid_dt = paid_at if isinstance(paid_at, datetime) else datetime.combine(
                    paid_at, datetime.min.time(), tzinfo=timezone.utc
                )
                weekday = paid_dt.astimezone(timezone.utc).weekday()
                amount_dec = Decimal(str(amount))
                weekday_counts[weekday] += 1
                weekday_amounts[weekday] += amount_dec
                if creator_id in by_rep:
                    count, total = by_rep[creator_id]
                    by_rep[creator_id] = (count + 1, total + amount_dec)

        weekday_sales = [
            {
                "weekday": idx,
                "paid_count": weekday_counts[idx],
                "paid_amount": float(weekday_amounts[idx].quantize(Decimal("0.01"))),
            }
            for idx in range(7)
        ]
        best_weekday: int | None = None
        best_count = 0
        best_amount = Decimal("0")
        for idx, count in enumerate(weekday_counts):
            amount = weekday_amounts[idx]
            if count > best_count or (count == best_count and amount > best_amount and count > 0):
                best_weekday = idx
                best_count = count
                best_amount = amount
        if best_count == 0:
            best_weekday = None

        team_paid_count = sum(count for count, _ in by_rep.values())
        team_paid_total = sum((total for _, total in by_rep.values()), Decimal("0"))
        team_commission = (Decimal(team_paid_count) * SALES_COMMISSION_PER_SALE_USD).quantize(
            Decimal("0.01")
        )

        leaderboard = []
        for rep_id, (count, total) in by_rep.items():
            rep = rep_by_id[rep_id]
            leaderboard.append(
                {
                    "user_id": rep_id,
                    "first_name": rep.first_name,
                    "last_name": rep.last_name,
                    "paid_count": count,
                    "paid_amount": float(total.quantize(Decimal("0.01"))),
                    "commission": float(
                        (Decimal(count) * SALES_COMMISSION_PER_SALE_USD).quantize(Decimal("0.01"))
                    ),
                }
            )
        leaderboard.sort(key=lambda item: (-item["paid_count"], -item["paid_amount"], item["first_name"]))

        return {
            "active_sales_reps": len(reps),
            "team_monthly_paid_count": team_paid_count,
            "team_monthly_paid_total": float(team_paid_total.quantize(Decimal("0.01"))),
            "team_monthly_commission": float(team_commission),
            "commission_per_sale": float(SALES_COMMISSION_PER_SALE_USD),
            "weekday_sales": weekday_sales,
            "best_weekday": best_weekday,
            "best_weekday_paid_count": best_count,
            "best_weekday_paid_amount": float(best_amount.quantize(Decimal("0.01"))),
            "leaderboard": leaderboard,
        }

    def _sales_monthly_commission(self, *, user_id: int, merchant_id: int) -> dict:
        """Comisión propia ($500) + override ($250) por pagos de subvendedores."""
        today = date.today()
        month_start = date(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        month_end = date(today.year, today.month, last_day)
        month_start_dt = datetime(today.year, today.month, 1, tzinfo=timezone.utc)

        day_col = cast(PaymentLink.paid_at, Date).label("day")
        def paid_rows_for(user_ids: list[int]) -> list:
            if not user_ids:
                return []
            return self.db.execute(
                select(
                    day_col,
                    func.coalesce(func.sum(PaymentLink.amount), 0),
                    func.count(PaymentLink.id),
                )
                .join(Prospect, Prospect.id == PaymentLink.prospect_id)
                .where(
                    PaymentLink.status == PaymentLinkStatus.PAID.value,
                    PaymentLink.paid_at.is_not(None),
                    PaymentLink.paid_at >= month_start_dt,
                    # La venta pertenece al vendedor asignado al prospecto,
                    # aunque otro usuario haya generado el link de pago.
                    Prospect.assigned_to_user_id.in_(user_ids),
                    PaymentLink.merchant_id == merchant_id,
                    PaymentLink.prospect_id.is_not(None),
                )
                .group_by(day_col)
                .order_by(day_col)
            ).all()

        rows = paid_rows_for([user_id])
        child_ids = [
            int(child_id)
            for child_id in self.db.execute(
                # La comisión histórica no desaparece si luego se desactiva al subvendedor.
                select(User.id).where(User.parent_user_id == user_id)
            ).scalars().all()
        ]
        override_rows = paid_rows_for(child_ids)

        by_day: dict[date, tuple[Decimal, int]] = {}
        for row in rows:
            day_value = row[0]
            if isinstance(day_value, datetime):
                day_value = day_value.date()
            by_day[day_value] = (Decimal(str(row[1])), int(row[2]))

        override_by_day: dict[date, int] = {}
        for row in override_rows:
            day_value = row[0]
            if isinstance(day_value, datetime):
                day_value = day_value.date()
            override_by_day[day_value] = int(row[2])

        series: list[dict] = []
        running_paid = Decimal("0")
        paid_count = 0
        override_paid_count = 0
        current = month_start
        while current <= month_end:
            # Días futuros: sin actividad; el acumulado se mantiene plano.
            if current <= today:
                day_paid, day_count = by_day.get(current, (Decimal("0"), 0))
                day_override_count = override_by_day.get(current, 0)
                running_paid += day_paid
                paid_count += day_count
                override_paid_count += day_override_count
            else:
                day_paid, day_count = Decimal("0"), 0
                day_override_count = 0
            daily_own = Decimal(day_count) * SALES_COMMISSION_PER_SALE_USD
            daily_override = Decimal(day_override_count) * PARENT_OVERRIDE_COMMISSION_PER_SALE_USD
            daily_commission = (daily_own + daily_override).quantize(Decimal("0.01"))
            cumulative_own = Decimal(paid_count) * SALES_COMMISSION_PER_SALE_USD
            cumulative_override = (
                Decimal(override_paid_count) * PARENT_OVERRIDE_COMMISSION_PER_SALE_USD
            )
            cumulative = (cumulative_own + cumulative_override).quantize(Decimal("0.01"))
            series.append(
                {
                    "date": current.isoformat(),
                    "daily_paid": float(day_paid),
                    "daily_commission": float(daily_commission),
                    "daily_own_commission": float(daily_own),
                    "daily_override_commission": float(daily_override),
                    "cumulative_commission": float(cumulative),
                }
            )
            current += timedelta(days=1)

        own_commission = (Decimal(paid_count) * SALES_COMMISSION_PER_SALE_USD).quantize(
            Decimal("0.01")
        )
        override_commission = (
            Decimal(override_paid_count) * PARENT_OVERRIDE_COMMISSION_PER_SALE_USD
        ).quantize(Decimal("0.01"))
        monthly_commission = own_commission + override_commission
        return {
            "monthly_paid_total": float(running_paid),
            "monthly_commission": float(monthly_commission),
            "commission_per_sale": float(SALES_COMMISSION_PER_SALE_USD),
            "parent_override_per_sale": float(PARENT_OVERRIDE_COMMISSION_PER_SALE_USD),
            "monthly_paid_count": paid_count,
            "override_paid_count": override_paid_count,
            "own_commission": float(own_commission),
            "override_commission": float(override_commission),
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
        prospects_by_influencer: list[dict] | None = None,
        scope: str = "general",
        sales_commission: dict | None = None,
    ) -> dict:
        if code == "VENTAS":
            return self._build_sales_area_metrics(
                name,
                prospects_by_status,
                prospects_by_source or {},
                scope,
                by_influencer=prospects_by_influencer or [],
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
            "by_influencer": [],
        }

    def _build_sales_area_metrics(
        self,
        name: str,
        by_status: dict[str, int],
        by_source: dict[str, int],
        scope: str,
        *,
        by_influencer: list[dict] | None = None,
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

        catalog_codes = _catalog_source_codes(self.db)
        ordered_codes = list(catalog_codes)
        for code in by_source:
            if code not in ordered_codes:
                ordered_codes.append(code)
        source_counts = [
            {"source": source, "count": by_source.get(source, 0)} for source in ordered_codes
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
            "by_influencer": by_influencer or [],
        }
        if sales_commission:
            metrics.update(sales_commission)
        return metrics
