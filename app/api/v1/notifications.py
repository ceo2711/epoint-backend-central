import asyncio
import json
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models.notification import Notification
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.notification import (
    NotificationDelete,
    NotificationMarkRead,
    NotificationResponse,
    PushDeviceTokenRegister,
    PushDeviceTokenUnregister,
)
from app.services.notifications import NotificationService
from app.services.notifications.hub import notification_hub

router = APIRouter(prefix="/notifications", tags=["Notificaciones"])

STREAM_POLL_SECONDS = 2
STREAM_HEARTBEAT_SECONDS = 25
NOTIFICATION_RETENTION_DAYS = 5


@router.get("/stream")
async def stream_notifications(request: Request, current_user: CurrentUser) -> StreamingResponse:
    async def event_generator():
        queue = notification_hub.subscribe(current_user.id)
        heartbeat_ticks = 0
        ticks_per_heartbeat = max(1, STREAM_HEARTBEAT_SECONDS // STREAM_POLL_SECONDS)
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=STREAM_POLL_SECONDS)
                except asyncio.TimeoutError:
                    heartbeat_ticks += 1
                    if heartbeat_ticks >= ticks_per_heartbeat:
                        heartbeat_ticks = 0
                        if await request.is_disconnected():
                            break
                        yield ": heartbeat\n\n"
                    continue

                heartbeat_ticks = 0
                if message.get("type") == "__shutdown__":
                    break
                yield f"data: {json.dumps(message, default=str)}\n\n"
        finally:
            notification_hub.unsubscribe(current_user.id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=PaginatedResponse[NotificationResponse])
def list_notifications(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
) -> PaginatedResponse[NotificationResponse]:
    service = NotificationService(db)
    query = service.apply_in_app_scope(select(Notification), current_user)
    since = datetime.now(timezone.utc) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    query = query.where(Notification.created_at >= since)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    items = (
        db.execute(
            query.order_by(Notification.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    return PaginatedResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.post("/mark-read", response_model=MessageResponse)
def mark_read(
    payload: NotificationMarkRead,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    service = NotificationService(db)
    query = service.apply_in_app_scope(
        select(Notification).where(Notification.id.in_(payload.notification_ids)),
        current_user,
    )
    notifications = db.execute(query).scalars().all()
    now = datetime.now(timezone.utc)
    for n in notifications:
        n.read_at = now
    db.commit()
    return MessageResponse(message=f"{len(notifications)} notificación(es) marcada(s) como leída(s)")


@router.post("/delete", response_model=MessageResponse)
def delete_notifications(
    payload: NotificationDelete,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    service = NotificationService(db)
    query = service.apply_in_app_scope(
        select(Notification).where(Notification.id.in_(payload.notification_ids)),
        current_user,
    )
    notifications = db.execute(query).scalars().all()
    for n in notifications:
        db.delete(n)
    db.commit()
    return MessageResponse(message=f"{len(notifications)} notificación(es) eliminada(s)")


@router.post("/device-token", response_model=MessageResponse)
def register_device_token(
    payload: PushDeviceTokenRegister,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    NotificationService(db).register_device_token(
        user_id=current_user.id,
        token=payload.token,
        platform=payload.platform,
    )
    return MessageResponse(message="Device token registrado")


@router.post("/device-token/unregister", response_model=MessageResponse)
def unregister_device_token(
    payload: PushDeviceTokenUnregister,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    removed = NotificationService(db).unregister_device_token(
        user_id=current_user.id,
        token=payload.token,
    )
    return MessageResponse(message=f"{removed} token(s) eliminado(s)")
