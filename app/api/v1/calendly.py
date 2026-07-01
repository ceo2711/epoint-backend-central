from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.calendly import (
    CalendlyAvailableTimeResponse,
    CalendlyConnectionResponse,
    CalendlyConnectRequest,
    CalendlyEventCancelRequest,
    CalendlyEventCreateRequest,
    CalendlyEventResponse,
    CalendlyEventTypeResponse,
    CalendlyEventUpdateRequest,
    CalendlySalesRepItem,
    CalendlySyncResponse,
)
from app.schemas.common import MessageResponse
from app.services.calendly.service import CalendlyService

router = APIRouter(prefix="/calendly", tags=["Calendly"])


@router.get("/sales-reps", response_model=list[CalendlySalesRepItem])
def list_sales_reps(current_user: CurrentUser, db: DbSession) -> list[CalendlySalesRepItem]:
    return CalendlyService(db).list_sales_reps(current_user)


@router.get("/connection", response_model=CalendlyConnectionResponse)
def get_connection(
    current_user: CurrentUser,
    db: DbSession,
    user_id: int | None = Query(default=None),
) -> CalendlyConnectionResponse:
    return CalendlyService(db).get_connection(current_user, user_id=user_id)


@router.post("/connection", response_model=CalendlyConnectionResponse)
def connect_calendly(
    payload: CalendlyConnectRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CalendlyConnectionResponse:
    return CalendlyService(db).connect(current_user, payload)


@router.delete("/connection", response_model=MessageResponse)
def disconnect_calendly(current_user: CurrentUser, db: DbSession) -> MessageResponse:
    return CalendlyService(db).disconnect(current_user)


@router.post("/sync", response_model=CalendlySyncResponse)
def sync_calendly(
    current_user: CurrentUser,
    db: DbSession,
    user_id: int | None = Query(default=None),
) -> CalendlySyncResponse:
    return CalendlyService(db).sync_events(current_user, user_id=user_id)


@router.get("/event-types", response_model=list[CalendlyEventTypeResponse])
def list_event_types(
    current_user: CurrentUser,
    db: DbSession,
    user_id: int | None = Query(default=None),
) -> list[CalendlyEventTypeResponse]:
    return CalendlyService(db).list_event_types(current_user, user_id=user_id)


@router.get("/event-types/detail", response_model=CalendlyEventTypeResponse)
def get_event_type_detail(
    current_user: CurrentUser,
    db: DbSession,
    event_type_uri: str = Query(min_length=10),
    user_id: int | None = Query(default=None),
) -> CalendlyEventTypeResponse:
    return CalendlyService(db).get_event_type_detail(
        current_user,
        event_type_uri=event_type_uri,
        user_id=user_id,
    )


@router.get("/available-times", response_model=list[CalendlyAvailableTimeResponse])
def list_available_times(
    current_user: CurrentUser,
    db: DbSession,
    event_type_uri: str = Query(min_length=10),
    start: datetime = Query(),
    end: datetime = Query(),
) -> list[CalendlyAvailableTimeResponse]:
    return CalendlyService(db).list_available_times(
        current_user,
        event_type_uri=event_type_uri,
        start=start,
        end=end,
    )


@router.get("/events", response_model=list[CalendlyEventResponse])
def list_events(
    current_user: CurrentUser,
    db: DbSession,
    user_id: int | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
) -> list[CalendlyEventResponse]:
    return CalendlyService(db).list_events(current_user, user_id=user_id, start=start, end=end)


@router.post("/events", response_model=CalendlyEventResponse)
def create_event(
    payload: CalendlyEventCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CalendlyEventResponse:
    return CalendlyService(db).create_event(current_user, payload)


@router.patch("/events/{event_id}", response_model=CalendlyEventResponse)
def update_event(
    event_id: int,
    payload: CalendlyEventUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CalendlyEventResponse:
    return CalendlyService(db).update_event(current_user, event_id, payload)


@router.delete("/events/{event_id}", response_model=MessageResponse)
def cancel_event(
    event_id: int,
    current_user: CurrentUser,
    db: DbSession,
    payload: CalendlyEventCancelRequest | None = None,
) -> MessageResponse:
    return CalendlyService(db).cancel_event(current_user, event_id, payload or CalendlyEventCancelRequest())
