from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    safe_decode_token,
    verify_password,
)
from app.models.session import UserSession
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshTokenRequest, TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.user import UserMeResponse, UserResponse
from app.api.deps import get_user_permissions

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = (
        db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(User.email == payload.email.lower())
        )
        .unique()
        .scalar_one_or_none()
    )

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    user.last_login_at = datetime.now(timezone.utc)
    access_token = create_access_token(
        str(user.id),
        extra_claims={"role": user.role.code},
    )
    refresh_token, jti = create_refresh_token(str(user.id))

    settings_expire = timedelta(days=7)
    session = UserSession(
        user_id=user.id,
        jti=jti,
        expires_at=datetime.now(timezone.utc) + settings_expire,
    )
    db.add(session)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshTokenRequest, db: DbSession) -> TokenResponse:
    token_payload = safe_decode_token(payload.refresh_token)
    if token_payload is None or token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    jti = token_payload.get("jti")
    user_id = token_payload.get("sub")
    if not jti or not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    session = db.execute(
        select(UserSession).where(UserSession.jti == jti, UserSession.is_revoked.is_(False))
    ).scalar_one_or_none()

    if session is None or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión expirada o revocada")

    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    access_token = create_access_token(str(user.id), extra_claims={"role": user.role.code})
    return TokenResponse(access_token=access_token, must_change_password=user.must_change_password)


@router.post("/logout", response_model=MessageResponse)
def logout(payload: RefreshTokenRequest, db: DbSession) -> MessageResponse:
    token_payload = safe_decode_token(payload.refresh_token)
    if token_payload and token_payload.get("jti"):
        session = db.execute(
            select(UserSession).where(UserSession.jti == token_payload["jti"])
        ).scalar_one_or_none()
        if session:
            session.is_revoked = True
            db.commit()
    return MessageResponse(message="Sesión cerrada")


@router.get("/me", response_model=UserMeResponse)
def get_me(current_user: CurrentUser, db: DbSession) -> UserMeResponse:
    permissions = get_user_permissions(db, current_user)
    base = UserResponse.model_validate(current_user)
    return UserMeResponse(**base.model_dump(), permissions=permissions)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    db.commit()
    return MessageResponse(message="Contraseña actualizada correctamente")
