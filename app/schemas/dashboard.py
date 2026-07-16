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


class TimeseriesPoint(BaseModel):
    date: str
    count: int


class ProjectionPoint(BaseModel):
    date: str
    projected: float


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
