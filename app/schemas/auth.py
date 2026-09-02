from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserMeResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class LoginResponse(BaseModel):
    requires_2fa: bool = False
    temp_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    must_change_password: bool = False
    user: UserMeResponse | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=8)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20)
    new_password: str = Field(min_length=8)


class TwoFactorVerifyRequest(BaseModel):
    temp_token: str
    code: str = Field(min_length=6, max_length=6)


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class SensitiveStepUpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class SensitiveStepUpResponse(BaseModel):
    token: str
    expires_in: int
