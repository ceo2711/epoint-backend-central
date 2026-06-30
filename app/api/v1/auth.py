from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    TokenResponse,
    TotpConfirmRequest,
    TotpDisableRequest,
    TotpSetupResponse,
    TwoFactorVerifyRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserMeResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession) -> LoginResponse:
    return AuthService(db).login(payload)


@router.post("/2fa/verify", response_model=LoginResponse)
def verify_2fa(payload: TwoFactorVerifyRequest, db: DbSession) -> LoginResponse:
    return AuthService(db).verify_2fa(payload)


@router.post("/2fa/setup", response_model=TotpSetupResponse)
def setup_2fa(current_user: CurrentUser, db: DbSession) -> TotpSetupResponse:
    return AuthService(db).setup_totp(current_user)


@router.post("/2fa/confirm", response_model=MessageResponse)
def confirm_2fa(
    payload: TotpConfirmRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    return AuthService(db).confirm_totp(current_user, payload)


@router.post("/2fa/disable", response_model=MessageResponse)
def disable_2fa(
    payload: TotpDisableRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    return AuthService(db).disable_totp(current_user, payload)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshTokenRequest, db: DbSession) -> TokenResponse:
    return AuthService(db).refresh_token(payload)


@router.post("/logout", response_model=MessageResponse)
def logout(payload: RefreshTokenRequest, db: DbSession) -> MessageResponse:
    return AuthService(db).logout(payload)


@router.get("/me", response_model=UserMeResponse)
def get_me(current_user: CurrentUser, db: DbSession) -> UserMeResponse:
    return AuthService(db).get_me(current_user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    return AuthService(db).change_password(current_user, payload)


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> MessageResponse:
    return AuthService(db).request_password_reset(payload)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> MessageResponse:
    return AuthService(db).reset_password(payload)
