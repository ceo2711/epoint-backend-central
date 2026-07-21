from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class SedeBrief(ORMBase):
    id: int
    code: str
    name: str


class SedeResponse(ORMBase):
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    avatar_url: str | None = None


class SedeCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class SedeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    is_active: bool | None = None
