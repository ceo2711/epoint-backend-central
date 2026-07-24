from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class SourceBrief(ORMBase):
    code: str
    name: str


class SourceResponse(ORMBase):
    id: int
    code: str
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime


class SourceCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    sort_order: int = 0


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
