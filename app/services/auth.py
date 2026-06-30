from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_user_permissions
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    safe_decode_token,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.session import UserSession
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserMeResponse, UserResponse
from app.services.email.password_reset import (
    PasswordResetEmailPayload,
    send_password_reset_email,
)

PASSWORD_RESET_SENT_MESSAGE = (
    "Si el correo está registrado, recibirás un enlace para restablecer tu contraseña."
)
CLIENT_ROLE_CODE = "CLIENT"


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _build_user_me(self, user: User) -> UserMeResponse:
        permissions = get_user_permissions(self.db, user)
        base = UserResponse.model_validate(user)
        return UserMeResponse(**base.model_dump(), permissions=permissions)

    def login(self, payload: LoginRequest) -> LoginResponse:
        user = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area))
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

        settings = get_settings()
        session = UserSession(
            user_id=user.id,
            jti=jti,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days),
        )
        self.db.add(session)
        self.db.commit()

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            must_change_password=user.must_change_password,
            user=self._build_user_me(user),
        )

    def refresh_token(self, payload: RefreshTokenRequest) -> TokenResponse:
        token_payload = safe_decode_token(payload.refresh_token)
        if token_payload is None or token_payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

        jti = token_payload.get("jti")
        user_id = token_payload.get("sub")
        if not jti or not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

        session = self.db.execute(
            select(UserSession).where(UserSession.jti == jti, UserSession.is_revoked.is_(False))
        ).scalar_one_or_none()

        if session is None or session.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión expirada o revocada")

        user = self.db.get(User, int(user_id))
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

        access_token = create_access_token(str(user.id), extra_claims={"role": user.role.code})
        return TokenResponse(access_token=access_token, must_change_password=user.must_change_password)

    def logout(self, payload: RefreshTokenRequest) -> MessageResponse:
        token_payload = safe_decode_token(payload.refresh_token)
        if token_payload and token_payload.get("jti"):
            session = self.db.execute(
                select(UserSession).where(UserSession.jti == token_payload["jti"])
            ).scalar_one_or_none()
            if session:
                session.is_revoked = True
                self.db.commit()
        return MessageResponse(message="Sesión cerrada")

    def get_me(self, user: User) -> UserMeResponse:
        return self._build_user_me(user)

    def change_password(self, user: User, payload: ChangePasswordRequest) -> MessageResponse:
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = False
        self.db.commit()
        return MessageResponse(message="Contraseña actualizada correctamente")

    def request_password_reset(self, payload: ForgotPasswordRequest) -> MessageResponse:
        user = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role))
                .where(User.email == payload.email.lower())
            )
            .unique()
            .scalar_one_or_none()
        )

        if user is not None and user.is_active and user.role.code == CLIENT_ROLE_CODE:
            settings = get_settings()
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=settings.password_reset_token_expire_minutes)

            for row in self.db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.used_at.is_(None),
                )
            ).scalars():
                row.used_at = now

            raw_token = generate_password_reset_token()
            self.db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_password_reset_token(raw_token),
                    expires_at=expires_at,
                )
            )
            self.db.commit()

            reset_url = (
                f"{settings.portal_base_url}/recuperar-contrasena/confirmar"
                f"?token={raw_token}"
            )
            send_password_reset_email(
                PasswordResetEmailPayload(
                    recipient_email=user.email,
                    first_name=user.first_name,
                    reset_url=reset_url,
                    expire_minutes=settings.password_reset_token_expire_minutes,
                )
            )

        return MessageResponse(message=PASSWORD_RESET_SENT_MESSAGE)

    def reset_password(self, payload: ResetPasswordRequest) -> MessageResponse:
        token_hash = hash_password_reset_token(payload.token.strip())
        now = datetime.now(timezone.utc)

        reset_row = self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        ).scalar_one_or_none()

        if reset_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El enlace de restablecimiento es inválido o expiró",
            )

        user = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role))
                .where(User.id == reset_row.user_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if user is None or not user.is_active or user.role.code != CLIENT_ROLE_CODE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El enlace de restablecimiento es inválido o expiró",
            )

        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = False
        reset_row.used_at = now

        sessions = self.db.execute(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.is_revoked.is_(False),
            )
        ).scalars()
        for session in sessions:
            session.is_revoked = True

        self.db.commit()
        return MessageResponse(message="Contraseña actualizada correctamente")
