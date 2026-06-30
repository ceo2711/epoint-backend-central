from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserMeResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class LoginResponse(TokenResponse):
    refresh_token: str
    user: UserMeResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=8)


class RefreshTokenRequest(BaseModel):
    refresh_token: str
