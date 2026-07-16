"""Tests for self profile update."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.schemas.user import UserProfileUpdate
from app.services.auth import AuthService


def _user(*, role_code: str = "ADMIN", email: str = "admin@epoint.com"):
    user = MagicMock()
    user.id = 1
    user.email = email
    user.first_name = "Administrador"
    user.last_name = "ePoint"
    user.role.code = role_code
    return user


def test_update_profile_rejects_non_admin():
    db = MagicMock()
    for role_code in ("CLIENT", "VENDEDOR", "SUPERVISOR"):
        with pytest.raises(HTTPException) as exc:
            AuthService(db).update_profile(_user(role_code=role_code), UserProfileUpdate(
                first_name="Ana",
                last_name="Usuario",
                email="ana@example.com",
            ))
        assert exc.value.status_code == 403


def test_update_profile_rejects_duplicate_email():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = MagicMock(id=2)
    with pytest.raises(HTTPException) as exc:
        AuthService(db).update_profile(_user(), UserProfileUpdate(
            first_name="Administrador",
            last_name="ePoint",
            email="otro@epoint.com",
        ))
    assert exc.value.status_code == 409


def test_update_profile_success():
    db = MagicMock()
    user = _user()
    service = AuthService(db)

    service._build_user_me = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]

    service.update_profile(user, UserProfileUpdate(
        first_name="Admin",
        last_name="Central",
        email="admin@epoint.com",
    ))

    assert user.first_name == "Admin"
    assert user.last_name == "Central"
    db.commit.assert_called_once()
    service._build_user_me.assert_called_once()
