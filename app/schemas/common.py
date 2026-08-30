from datetime import datetime
from typing import Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class SendCustomEmailRequest(BaseModel):
    subject: str
    message_html: str


class SentEmailResponse(BaseModel):
    id: int
    subject: str
    message_html: str
    recipient_email: str
    sent_by_name: str
    created_at: datetime
    direction: str = "OUTBOUND"
    read_at: datetime | None = None
    from_email: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
