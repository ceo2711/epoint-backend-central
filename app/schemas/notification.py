from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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


class NotificationDelete(BaseModel):
    notification_ids: list[int] = Field(min_length=1)


class PushDeviceTokenRegister(BaseModel):
    token: str = Field(min_length=10, max_length=512)
    platform: Literal["ios", "android", "web"]


class PushDeviceTokenUnregister(BaseModel):
    token: str = Field(min_length=10, max_length=512)
