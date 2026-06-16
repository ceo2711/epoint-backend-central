from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    create_refresh_token,
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
        db.commit.assert_called_once()

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
