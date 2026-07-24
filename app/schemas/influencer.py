from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class InfluencerBrief(ORMBase):
    id: int
    name: str
    handle: str | None = None
    sales_rep_user_id: int
    sales_rep_name: str | None = None


class InfluencerResponse(ORMBase):
    id: int
    name: str
    handle: str | None
    notes: str | None
    sede_id: int
    sede_name: str | None = None
    sales_rep_user_id: int
    sales_rep_name: str | None = None
    is_active: bool
    created_at: datetime


class InfluencerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    handle: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    sales_rep_user_id: int
    sede_id: int | None = None


class InfluencerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    handle: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    sales_rep_user_id: int | None = None
    is_active: bool | None = None
