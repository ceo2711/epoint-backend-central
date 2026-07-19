from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_user_permissions
from app.core.config import get_settings
from app.core.security import (
    create_2fa_pending_token,
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
    TotpConfirmRequest,
    TotpSetupResponse,
    TwoFactorVerifyRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.client import MerchantBrief
from app.schemas.user import UserMeResponse, UserProfileUpdate, UserResponse
from app.services.merchant_context import MerchantContextService
from app.services.email.password_reset import (
    PasswordResetEmailPayload,
    send_password_reset_email,
)
from app.services.totp import (
    build_provisioning_uri,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    verify_totp_code,
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
        ctx = MerchantContextService(self.db)
        merchants = ctx.list_accessible_merchants(user) if ctx.is_staff(user) else []
        merchant_briefs = [MerchantBrief.model_validate(m) for m in merchants]
        active_merchant = None
        active_merchant_id = user.active_merchant_id
        if merchants:
            if active_merchant_id is not None:
                active_merchant = next((m for m in merchants if m.id == active_merchant_id), None)
            if active_merchant is None and len(merchants) == 1:
                active_merchant = merchants[0]
                active_merchant_id = active_merchant.id
        return UserMeResponse(
            **base.model_dump(),
            permissions=permissions,
            merchants=merchant_briefs,
            active_merchant_id=active_merchant_id,
            active_merchant=MerchantBrief.model_validate(active_merchant) if active_merchant else None,
        )

    def set_active_merchant(self, user: User, merchant_id: int) -> UserMeResponse:
        MerchantContextService(self.db).set_active_merchant(user, merchant_id)
        refreshed = self.db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.area))
            .where(User.id == user.id)
        ).unique().scalar_one()
        return self._build_user_me(refreshed)

    def _issue_session_tokens(self, user: User) -> tuple[str, str]:
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
        return access_token, refresh_token

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
        self.db.commit()

        if user.totp_enabled:
            temp_token = create_2fa_pending_token(
                str(user.id),
                extra_claims={"role": user.role.code},
            )
            return LoginResponse(
                requires_2fa=True,
                temp_token=temp_token,
                must_change_password=user.must_change_password,
                user=self._build_user_me(user),
            )

        access_token, refresh_token = self._issue_session_tokens(user)
        self.db.commit()

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            must_change_password=user.must_change_password,
            user=self._build_user_me(user),
        )

    def verify_2fa(self, payload: TwoFactorVerifyRequest) -> LoginResponse:
        token_payload = safe_decode_token(payload.temp_token)
        if token_payload is None or token_payload.get("type") != "2fa_pending":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión 2FA inválida o expirada")

        user_id = token_payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión 2FA inválida o expirada")

        user = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area))
                .where(User.id == int(user_id))
            )
            .unique()
            .scalar_one_or_none()
        )
        if user is None or not user.is_active or not user.totp_enabled or not user.totp_secret_encrypted:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión 2FA inválida o expirada")

        secret = decrypt_totp_secret(user.totp_secret_encrypted)
        if not verify_totp_code(secret=secret, code=payload.code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código de verificación inválido")

        access_token, refresh_token = self._issue_session_tokens(user)
        self.db.commit()

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            must_change_password=user.must_change_password,
            user=self._build_user_me(user),
        )

    def setup_totp(self, user: User) -> TotpSetupResponse:
        if user.totp_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El doble factor ya está activado",
            )

        secret = generate_totp_secret()
        user.totp_secret_encrypted = encrypt_totp_secret(secret)
        user.totp_confirmed_at = None
        self.db.commit()

        return TotpSetupResponse(
            secret=secret,
            provisioning_uri=build_provisioning_uri(email=user.email, secret=secret),
        )

    def confirm_totp(self, user: User, payload: TotpConfirmRequest) -> MessageResponse:
        if user.totp_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El doble factor ya está activado",
            )
        if not user.totp_secret_encrypted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Primero debés iniciar la configuración del doble factor",
            )

        secret = decrypt_totp_secret(user.totp_secret_encrypted)
        if not verify_totp_code(secret=secret, code=payload.code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código de verificación inválido")

        user.totp_enabled = True
        user.totp_confirmed_at = datetime.now(timezone.utc)
        self.db.commit()
        return MessageResponse(message="Doble factor activado correctamente")

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

    def update_profile(self, user: User, payload: UserProfileUpdate) -> UserMeResponse:
        if user.role.code != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un administrador puede modificar los datos personales",
            )

        normalized_email = payload.email.lower().strip()
        if normalized_email != user.email:
            existing = self.db.execute(
                select(User).where(User.email == normalized_email, User.id != user.id)
            ).scalar_one_or_none()
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="El email ya está registrado",
                )

        user.first_name = payload.first_name.strip()
        user.last_name = payload.last_name.strip()
        user.email = normalized_email
        self.db.commit()

        refreshed = self.db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.area))
            .where(User.id == user.id)
        ).unique().scalar_one()
        return self._build_user_me(refreshed)

    def change_password(self, user: User, payload: ChangePasswordRequest) -> MessageResponse:
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = False
        self._clear_client_portal_temp_password(user)
        self.db.commit()
        return MessageResponse(message="Contraseña actualizada correctamente")

    def _clear_client_portal_temp_password(self, user: User) -> None:
        """Si el cliente ya eligió su propia clave, la temporal deja de ser válida."""
        role_code = user.role.code if user.role is not None else None
        if role_code is None:
            # Asegurar rol cargado en sesiones parciales
            self.db.refresh(user, attribute_names=["role"])
            role_code = user.role.code if user.role is not None else None
        if role_code != CLIENT_ROLE_CODE or user.client_id is None:
            return
        from app.models.client import Client

        client = self.db.get(Client, user.client_id)
        if client is not None and client.portal_temp_password_encrypted is not None:
            client.portal_temp_password_encrypted = None

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
        self._clear_client_portal_temp_password(user)
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
