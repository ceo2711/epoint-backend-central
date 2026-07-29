from pydantic import BaseModel, Field

from app.schemas.client import ClientStatsResponse


class MerchantScope(BaseModel):
    id: int
    code: str
    name: str


class StatusCount(BaseModel):
    status: str
    count: int


class SourceCount(BaseModel):
    source: str
    count: int


class InfluencerLeadCount(BaseModel):
    influencer_id: int
    name: str
    handle: str | None = None
    count: int
    converted_count: int = 0


class TimeseriesPoint(BaseModel):
    date: str
    count: int


class ProjectionPoint(BaseModel):
    date: str
    projected: float


class CommissionDayPoint(BaseModel):
    date: str
    daily_paid: float
    daily_commission: float
    daily_own_commission: float = 0.0
    daily_override_commission: float = 0.0
    cumulative_commission: float


class WeekdaySalesPoint(BaseModel):
    """Ventas por día de la semana (0=lunes … 6=domingo). Solo líder de ventas."""

    weekday: int
    paid_count: int
    paid_amount: float


class SalesRepLeaderboardItem(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    paid_count: int
    paid_amount: float
    commission: float


class SalesLeadershipMetrics(BaseModel):
    """KPIs de supervisión del líder de área de Ventas (equipo completo)."""

    active_sales_reps: int
    team_monthly_paid_count: int
    team_monthly_paid_total: float
    team_monthly_commission: float
    commission_per_sale: float
    weekday_sales: list[WeekdaySalesPoint] = Field(default_factory=list)
    best_weekday: int | None = None
    best_weekday_paid_count: int = 0
    best_weekday_paid_amount: float = 0.0
    leaderboard: list[SalesRepLeaderboardItem] = Field(default_factory=list)


class AreaMetrics(BaseModel):
    code: str
    name: str
    scope: str = "general"
    total: int
    in_pipeline: int
    completed: int
    conversion_rate: float | None = None
    by_status: list[StatusCount]
    by_source: list[SourceCount] = Field(default_factory=list)
    by_influencer: list[InfluencerLeadCount] = Field(default_factory=list)
    # Comisión del vendedor (solo scope personal / SALES_REP)
    monthly_paid_total: float | None = None
    monthly_commission: float | None = None
    commission_per_sale: float | None = None
    parent_override_per_sale: float | None = None
    monthly_paid_count: int | None = None
    override_paid_count: int | None = None
    own_commission: float | None = None
    override_commission: float | None = None
    commission_series: list[CommissionDayPoint] = Field(default_factory=list)


class DashboardMetricsResponse(BaseModel):
    merchant: MerchantScope
    viewer_scope: str = "general"
    summary: ClientStatsResponse
    by_status: dict[str, int]
    areas: list[AreaMetrics]
    registrations: list[TimeseriesPoint] = Field(default_factory=list)
    prospect_registrations: list[TimeseriesPoint] = Field(default_factory=list)
    completions: list[TimeseriesPoint] = Field(default_factory=list)
    registration_projections: list[ProjectionPoint] = Field(default_factory=list)
    prospect_registration_projections: list[ProjectionPoint] = Field(default_factory=list)
    completion_projections: list[ProjectionPoint] = Field(default_factory=list)
    sales_leadership: SalesLeadershipMetrics | None = None
