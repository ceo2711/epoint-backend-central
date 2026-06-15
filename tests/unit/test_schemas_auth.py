import pytest
from pydantic import ValidationError

from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshTokenRequest


class TestLoginRequest:
    def test_valid_login_request(self):
        payload = LoginRequest(email="user@test.com", password="secret12")
        assert payload.email == "user@test.com"
        assert payload.password == "secret12"

    def test_password_min_length(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="user@test.com", password="12345")

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="not-an-email", password="secret12")


class TestChangePasswordRequest:
    def test_new_password_min_length(self):
        with pytest.raises(ValidationError):
            ChangePasswordRequest(current_password="oldpass1", new_password="short")

    def test_valid_change_password(self):
        payload = ChangePasswordRequest(current_password="oldpass1", new_password="newpass12")
        assert payload.new_password == "newpass12"


class TestRefreshTokenRequest:
    def test_requires_refresh_token(self):
        with pytest.raises(ValidationError):
            RefreshTokenRequest()

    def test_valid_refresh_token(self):
        payload = RefreshTokenRequest(refresh_token="abc.def.ghi")
        assert payload.refresh_token == "abc.def.ghi"
