from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMBase


class NotificationResponse(ORMBase):
    id: int
    event_type: str
    channel: str
    title: str
    body: str
    payload: dict[str, Any] | None
    status: str
    read_at: datetime | None
    created_at: datetime


class NotificationMarkRead(BaseModel):
    notification_ids: list[int]
