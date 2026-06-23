from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class MerchantResponse(ORMBase):
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime


class MerchantCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class MerchantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    is_active: bool | None = None
