from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_sensitive_step_up_token,
    hash_password,
    safe_decode_token,
    verify_password,
)
from app.schemas.auth import LoginRequest
from app.services.auth import AuthService


class TestPasswordHashing:
    def test_hash_and_verify_password(self):
        hashed = hash_password("SecurePass123!")
        assert hashed != "SecurePass123!"
        assert verify_password("SecurePass123!", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("CorrectPassword")
        assert verify_password("WrongPassword", hashed) is False


class TestJwtTokens:
    def test_create_access_token_decodable(self):
        token = create_access_token("42", extra_claims={"role": "ADMIN"})
        payload = safe_decode_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["type"] == "access"
        assert payload["role"] == "ADMIN"

    def test_create_refresh_token_has_jti(self):
        token, jti = create_refresh_token("99")
        payload = safe_decode_token(token)
        assert payload is not None
        assert payload["type"] == "refresh"
        assert payload["jti"] == jti
        assert payload["sub"] == "99"

    def test_safe_decode_invalid_token_returns_none(self):
        assert safe_decode_token("not-a-valid-jwt") is None

    def test_sensitive_step_up_token_type(self):
        token = create_sensitive_step_up_token("7")
        payload = safe_decode_token(token)
        assert payload is not None
        assert payload["type"] == "sensitive_step_up"
        assert payload["sub"] == "7"


class TestAuthServiceLogin:
    def _make_user(self, *, active: bool = True, password: str = "Admin123!"):
        role = MagicMock()
        role.code = "ADMIN"
        user = MagicMock()
        user.id = 1
        user.email = "admin@test.com"
        user.password_hash = hash_password(password)
        user.is_active = active
        user.must_change_password = False
        user.totp_enabled = False
        user.parent_user_id = None
        user.role = role
        user.area = None
        return user

    def test_login_success(self):
        user = self._make_user()
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.unique.return_value.scalar_one_or_none.return_value = user
        db.execute.return_value = result_mock

        from datetime import datetime, timezone

        from app.schemas.user import UserMeResponse, RoleBrief

        user_me = UserMeResponse(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="Test",
            phone=None,
            role=RoleBrief(id=1, code="ADMIN", name="Admin"),
            area=None,
            client_id=None,
            must_change_password=False,
            totp_enabled=False,
            is_active=True,
            last_login_at=None,
            created_at=datetime.now(timezone.utc),
            permissions=["users:read"],
        )

        with patch.object(AuthService, "_build_user_me", return_value=user_me):
            response = AuthService(db).login(LoginRequest(email="admin@test.com", password="Admin123!"))

        assert response.access_token
        assert response.refresh_token
        assert response.user.email == "admin@test.com"
        db.add.assert_called_once()
        assert db.commit.call_count >= 1

    def test_login_invalid_credentials(self):
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.unique.return_value.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        with pytest.raises(HTTPException) as exc:
            AuthService(db).login(LoginRequest(email="wrong@test.com", password="Admin123!"))

        assert exc.value.status_code == 401

    def test_login_inactive_user(self):
        user = self._make_user(active=False)
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.unique.return_value.scalar_one_or_none.return_value = user
        db.execute.return_value = result_mock

        with pytest.raises(HTTPException) as exc:
            AuthService(db).login(LoginRequest(email="admin@test.com", password="Admin123!"))

        assert exc.value.status_code == 403

    def test_login_requires_2fa_for_regular_user(self):
        user = self._make_user()
        user.email = "client@test.com"
        user.totp_enabled = True
        user.parent_user_id = None
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.unique.return_value.scalar_one_or_none.return_value = user
        db.execute.return_value = result_mock

        from datetime import datetime, timezone

        from app.schemas.user import RoleBrief, UserMeResponse

        pending = UserMeResponse(
            id=1,
            email="client@test.com",
            first_name="Client",
            last_name="Test",
            phone=None,
            role=RoleBrief(id=2, code="CLIENT", name="Cliente"),
            area=None,
            client_id=10,
            must_change_password=False,
            totp_enabled=True,
            is_active=True,
            last_login_at=None,
            created_at=datetime.now(timezone.utc),
        )

        with patch.object(AuthService, "_build_2fa_pending_user", return_value=pending):
            response = AuthService(db).login(
                LoginRequest(email="client@test.com", password="Admin123!")
            )

        assert response.requires_2fa is True
        assert response.temp_token
        assert response.access_token is None

    def test_login_skips_2fa_for_app_review_user(self):
        user = self._make_user()
        user.email = "appreview@epoint.com"
        user.totp_enabled = True
        user.must_change_password = True
        user.parent_user_id = None
        role = MagicMock()
        role.code = "CLIENT"
        user.role = role
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.unique.return_value.scalar_one_or_none.return_value = user
        db.execute.return_value = result_mock

        from datetime import datetime, timezone

        from app.schemas.user import RoleBrief, UserMeResponse

        user_me = UserMeResponse(
            id=1,
            email="appreview@epoint.com",
            first_name="App",
            last_name="Review",
            phone=None,
            role=RoleBrief(id=2, code="CLIENT", name="Cliente"),
            area=None,
            client_id=10,
            must_change_password=False,
            totp_enabled=False,
            is_active=True,
            last_login_at=None,
            created_at=datetime.now(timezone.utc),
        )

        with patch.object(AuthService, "_build_user_me", return_value=user_me):
            response = AuthService(db).login(
                LoginRequest(email="appreview@epoint.com", password="Admin123!")
            )

        assert response.requires_2fa is False
        assert response.access_token
        assert response.must_change_password is False


class TestAuthServiceChangePassword:
    def test_change_password_success(self):
        user = MagicMock()
        user.password_hash = hash_password("OldPass123!")
        user.must_change_password = True
        db = MagicMock()

        from app.schemas.auth import ChangePasswordRequest

        result = AuthService(db).change_password(
            user,
            ChangePasswordRequest(current_password="OldPass123!", new_password="NewPass1234"),
        )

        assert result.message == "Contraseña actualizada correctamente"
        assert user.must_change_password is False
        assert verify_password("NewPass1234", user.password_hash)
        db.commit.assert_called_once()

    def test_change_password_wrong_current(self):
        user = MagicMock()
        user.password_hash = hash_password("OldPass123!")
        db = MagicMock()

        from app.schemas.auth import ChangePasswordRequest

        with pytest.raises(HTTPException) as exc:
            AuthService(db).change_password(
                user,
                ChangePasswordRequest(current_password="WrongPass!", new_password="NewPass1234"),
            )

        assert exc.value.status_code == 400


class TestNeedsFirstSteps:
    def test_new_client_needs_first_steps(self):
        user = MagicMock()
        user.role.code = "CLIENT"
        user.email = "nuevo@test.com"
        user.first_steps_completed_at = None
        assert AuthService._needs_first_steps(user) is True

    def test_completed_client_does_not_need_first_steps(self):
        user = MagicMock()
        user.role.code = "CLIENT"
        user.email = "cliente@test.com"
        user.first_steps_completed_at = datetime.now(timezone.utc)
        assert AuthService._needs_first_steps(user) is False

    def test_staff_does_not_need_first_steps(self):
        user = MagicMock()
        user.role.code = "ADMIN"
        user.email = "admin@test.com"
        user.first_steps_completed_at = None
        assert AuthService._needs_first_steps(user) is False

    def test_app_review_client_skips_first_steps(self):
        user = MagicMock()
        user.role.code = "CLIENT"
        user.email = "appreview@epoint.com"
        user.first_steps_completed_at = None
        assert AuthService._needs_first_steps(user) is False


class TestCompleteFirstSteps:
    def _client_user(self):
        user = MagicMock()
        user.id = 10
        user.role.code = "CLIENT"
        user.email = "nuevo@test.com"
        user.first_steps_completed_at = None
        return user

    def test_sets_timestamp_for_client(self):
        from app.schemas.user import RoleBrief, UserMeResponse

        user = self._client_user()
        db = MagicMock()
        refreshed = MagicMock()
        db.execute.return_value.unique.return_value.scalar_one.return_value = refreshed
        user_me = UserMeResponse(
            id=10,
            email="nuevo@test.com",
            first_name="Nuevo",
            last_name="Cliente",
            phone=None,
            role=RoleBrief(id=2, code="CLIENT", name="Cliente"),
            area=None,
            client_id=20,
            must_change_password=False,
            totp_enabled=False,
            is_active=True,
            last_login_at=None,
            created_at=datetime.now(timezone.utc),
            needs_first_steps=False,
        )

        with patch.object(AuthService, "_build_user_me", return_value=user_me) as build:
            result = AuthService(db).complete_first_steps(user)

        assert user.first_steps_completed_at is not None
        db.commit.assert_called_once()
        build.assert_called_once_with(refreshed)
        assert result.needs_first_steps is False

    def test_idempotent_when_already_completed(self):
        from app.schemas.user import RoleBrief, UserMeResponse

        already = datetime.now(timezone.utc)
        user = self._client_user()
        user.first_steps_completed_at = already
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalar_one.return_value = user
        user_me = UserMeResponse(
            id=10,
            email="nuevo@test.com",
            first_name="Nuevo",
            last_name="Cliente",
            phone=None,
            role=RoleBrief(id=2, code="CLIENT", name="Cliente"),
            area=None,
            client_id=20,
            must_change_password=False,
            totp_enabled=False,
            is_active=True,
            last_login_at=None,
            created_at=datetime.now(timezone.utc),
            first_steps_completed_at=already,
            needs_first_steps=False,
        )

        with patch.object(AuthService, "_build_user_me", return_value=user_me):
            AuthService(db).complete_first_steps(user)

        assert user.first_steps_completed_at is already
        db.commit.assert_not_called()

    def test_rejects_staff(self):
        user = MagicMock()
        user.role.code = "ADMIN"
        db = MagicMock()

        with pytest.raises(HTTPException) as exc:
            AuthService(db).complete_first_steps(user)

        assert exc.value.status_code == 403
        db.commit.assert_not_called()
