from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ActiveMerchantId, DbSession, require_permissions
from app.models.user import User
from app.schemas.dashboard import DashboardMetricsResponse
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/metrics", response_model=DashboardMetricsResponse)
def get_dashboard_metrics(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
    sede_id: int | None = Query(None, description="Filtrar métricas por sede (admin global)"),
) -> DashboardMetricsResponse:
    service = DashboardService(db)
    return DashboardMetricsResponse(
        **service.get_metrics(
            current_user,
            merchant_id=merchant_id,
            filter_sede_id=sede_id,
        )
    )