import math
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models.notification import Notification
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.notification import NotificationMarkRead, NotificationResponse

router = APIRouter(prefix="/notifications", tags=["Notificaciones"])


@router.get("", response_model=PaginatedResponse[NotificationResponse])
def list_notifications(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
) -> PaginatedResponse[NotificationResponse]:
    query = select(Notification).where(
        Notification.user_id == current_user.id,
        Notification.channel == "IN_APP",
    )
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
    notifications = (
        db.execute(
            select(Notification).where(
                Notification.id.in_(payload.notification_ids),
                Notification.user_id == current_user.id,
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    for n in notifications:
        n.read_at = now
    db.commit()
    return MessageResponse(message=f"{len(notifications)} notificación(es) marcada(s) como leída(s)")
