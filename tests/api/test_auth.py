from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.auth import LoginResponse, TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.user import RoleBrief, UserMeResponse


@pytest.fixture
def client():
    return TestClient(app)


def _sample_user_me() -> UserMeResponse:
    return UserMeResponse(
        id=1,
        email="admin@test.com",
        first_name="Admin",
        last_name="User",
        phone=None,
        role=RoleBrief(id=1, code="ADMIN", name="Administrador"),
        area=None,
        client_id=None,
        must_change_password=False,
        is_active=True,
        last_login_at=None,
        created_at=datetime.now(timezone.utc),
        permissions=["users:read"],
    )


class TestAuthRoutes:
    def test_login_endpoint(self, client):
        mock_response = LoginResponse(
            access_token="fake-token",
            must_change_password=False,
            user=_sample_user_me(),
        )
        with patch("app.api.v1.auth.AuthService") as mock_service:
            mock_service.return_value.login.return_value = mock_response
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "admin@test.com", "password": "Admin123!"},
            )

        assert response.status_code == 200
        assert response.json()["access_token"] == "fake-token"
        mock_service.return_value.login.assert_called_once()

    def test_refresh_endpoint(self, client):
        mock_response = TokenResponse(access_token="new-token", must_change_password=False)
        with patch("app.api.v1.auth.AuthService") as mock_service:
            mock_service.return_value.refresh_token.return_value = mock_response
            response = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "refresh.jwt.token"},
            )

        assert response.status_code == 200
        assert response.json()["access_token"] == "new-token"

    def test_logout_endpoint(self, client):
        with patch("app.api.v1.auth.AuthService") as mock_service:
            mock_service.return_value.logout.return_value = MessageResponse(message="Sesión cerrada")
            response = client.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "refresh.jwt.token"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Sesión cerrada"

    def test_login_validation_error(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "not-email", "password": "123"},
        )
        assert response.status_code == 422
