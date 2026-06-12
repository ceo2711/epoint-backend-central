from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class PermissionResponse(ORMBase):
    id: int
    code: str
    name: str


class RoleResponse(ORMBase):
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    permissions: list[PermissionResponse] = []


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    is_active: bool | None = None
    permission_ids: list[int] | None = None
