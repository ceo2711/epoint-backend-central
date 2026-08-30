from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.constants.default_board_cards import EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL
from app.services.staff_users import StaffUserService


def _user(*, user_id: int, role: str, email: str = "user@epoint.com", is_active: bool = True):
    return SimpleNamespace(
        id=user_id,
        email=email,
        role=SimpleNamespace(code=role),
        is_active=is_active,
        avatar_storage_key=None,
    )


def test_delete_staff_user_rejects_non_admin():
    service = StaffUserService(MagicMock())
    actor = _user(user_id=1, role="BRANCH_MANAGER")
    target = _user(user_id=2, role="SALES_REP")

    with pytest.raises(HTTPException) as exc:
        service.delete_staff_user(actor, target)

    assert exc.value.status_code == 403
    service.db.delete.assert_not_called()


def test_delete_staff_user_rejects_self():
    service = StaffUserService(MagicMock())
    actor = _user(user_id=7, role="ADMIN")

    with pytest.raises(HTTPException) as exc:
        service.delete_staff_user(actor, actor)

    assert exc.value.status_code == 400
    assert "propia" in exc.value.detail


def test_delete_staff_user_rejects_system_account():
    service = StaffUserService(MagicMock())
    actor = _user(user_id=1, role="ADMIN")
    target = _user(user_id=9, role="ADVISOR", email=EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL)

    with pytest.raises(HTTPException) as exc:
        service.delete_staff_user(actor, target)

    assert exc.value.status_code == 400
    assert "sistema" in exc.value.detail


def test_delete_staff_user_hides_portal_clients():
    service = StaffUserService(MagicMock())
    actor = _user(user_id=1, role="ADMIN")
    target = _user(user_id=3, role="CLIENT")

    with pytest.raises(HTTPException) as exc:
        service.delete_staff_user(actor, target)

    assert exc.value.status_code == 404


def test_delete_staff_user_rejects_last_active_admin():
    db = MagicMock()
    db.execute.return_value.scalar.return_value = 0
    service = StaffUserService(db)
    actor = _user(user_id=1, role="ADMIN")
    target = _user(user_id=2, role="ADMIN")

    with pytest.raises(HTTPException) as exc:
        service.delete_staff_user(actor, target)

    assert exc.value.status_code == 400
    assert "último administrador" in exc.value.detail
    db.delete.assert_not_called()


@patch("app.services.staff_users.get_storage_provider")
def test_delete_staff_user_success(_storage):
    db = MagicMock()
    db.execute.return_value.scalar.return_value = 2
    service = StaffUserService(db)
    actor = _user(user_id=1, role="ADMIN")
    target = _user(user_id=4, role="SALES_REP", email="vendedor@epoint.com")

    service.delete_staff_user(actor, target)

    db.delete.assert_called_once_with(target)
    db.flush.assert_called_once()
    db.commit.assert_called_once()
