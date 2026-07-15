from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMBase
from app.schemas.client import MerchantBrief


class RoleBrief(ORMBase):
    id: int
    code: str
    name: str


class AreaBrief(ORMBase):
    id: int
    code: str
    name: str


class UserResponse(ORMBase):
    id: int
    email: str
    first_name: str
    last_name: str
    phone: str | None
    role: RoleBrief
    area: AreaBrief | None
    client_id: int | None = None
    must_change_password: bool
    totp_enabled: bool = False
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = None
    role_id: int
    area_id: int | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = None
    role_id: int | None = None
    area_id: int | None = None
    is_active: bool | None = None


class UserMeResponse(UserResponse):
    permissions: list[str] = []
    merchants: list[MerchantBrief] = []
    active_merchant_id: int | None = None
    active_merchant: MerchantBrief | None = None


class SetActiveMerchantRequest(BaseModel):
    merchant_id: int


class UserProfileUpdate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
