from fastapi import APIRouter, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    TokenResponse,
    TotpConfirmRequest,
    TotpSetupResponse,
    TwoFactorVerifyRequest,
    SensitiveStepUpRequest,
    SensitiveStepUpResponse,
)
from app.schemas.common import MessageResponse
from app.schemas.user import (
    BootstrapAdminCreate,
    SetActiveMerchantRequest,
    UserMeResponse,
    UserProfileUpdate,
    UserResponse,
)
from app.services.auth import AuthService
from app.services.user_serialization import serialize_user

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession) -> LoginResponse:
    return AuthService(db).login(payload)


@router.post(
    "/bootstrap-admin",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear usuario ADMIN (token de bootstrap)",
)
def bootstrap_admin(
    payload: BootstrapAdminCreate,
    db: DbSession,
    x_bootstrap_token: str | None = Header(default=None, alias="X-Bootstrap-Token"),
) -> UserResponse:
    """Crea un ADMIN sin sesión JWT. Requiere header ``X-Bootstrap-Token`` =
    env ``BOOTSTRAP_ADMIN_TOKEN``. Si el token no está configurado, responde 404.
    """
    settings = get_settings()
    expected = (settings.bootstrap_admin_token or "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not x_bootstrap_token or x_bootstrap_token.strip() != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token inválido")

    email = payload.email.lower().strip()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya está registrado")

    role = db.execute(select(Role).where(Role.code == "ADMIN")).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rol ADMIN no existe. Ejecutá scripts/seed.py primero.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        phone=payload.phone,
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    user = (
        db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
            .where(User.id == user.id)
        )
        .unique()
        .scalar_one()
    )
    return serialize_user(user)


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


@router.post("/2fa/step-up", response_model=SensitiveStepUpResponse)
def step_up_2fa(
    payload: SensitiveStepUpRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> SensitiveStepUpResponse:
    return AuthService(db).verify_sensitive_step_up(current_user, payload)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshTokenRequest, db: DbSession) -> TokenResponse:
    return AuthService(db).refresh_token(payload)


@router.post("/logout", response_model=MessageResponse)
def logout(payload: RefreshTokenRequest, db: DbSession) -> MessageResponse:
    return AuthService(db).logout(payload)


@router.get("/me", response_model=UserMeResponse)
def get_me(current_user: CurrentUser, db: DbSession) -> UserMeResponse:
    return AuthService(db).get_me(current_user)


@router.patch("/me", response_model=UserMeResponse)
def update_me(
    payload: UserProfileUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> UserMeResponse:
    return AuthService(db).update_profile(current_user, payload)


@router.post("/me/avatar", response_model=UserMeResponse)
async def upload_my_avatar(
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
) -> UserMeResponse:
    file_bytes = await file.read()
    return AuthService(db).upload_avatar(
        current_user,
        filename=file.filename or "avatar.jpg",
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
    )


@router.delete("/me/avatar", response_model=UserMeResponse)
def delete_my_avatar(current_user: CurrentUser, db: DbSession) -> UserMeResponse:
    return AuthService(db).delete_avatar(current_user)


@router.put("/me/active-merchant", response_model=UserMeResponse)
def set_active_merchant(
    payload: SetActiveMerchantRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> UserMeResponse:
    return AuthService(db).set_active_merchant(current_user, payload.merchant_id)


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
