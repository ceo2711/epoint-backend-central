"""Tests for active merchant context (EC-57)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.merchant_context import MerchantContextService


def _merchant(id: int, *, active: bool = True):
    merchant = MagicMock()
    merchant.id = id
    merchant.is_active = active
    merchant.name = f"Merchant {id}"
    return merchant


def _user(role_code: str = "SALES_REP", *, active_merchant_id: int | None = 1):
    user = MagicMock()
    user.id = 10
    user.role.code = role_code
    user.active_merchant_id = active_merchant_id
    return user


def test_list_accessible_merchants_for_admin_returns_all_active():
    db = MagicMock()
    merchants = [_merchant(1), _merchant(2)]
    db.execute.return_value.scalars.return_value.all.return_value = merchants

    result = MerchantContextService(db).list_accessible_merchants(_user("ADMIN"))

    assert [m.id for m in result] == [1, 2]


def test_list_accessible_merchants_for_branch_manager_returns_all_active():
    db = MagicMock()
    merchants = [_merchant(1), _merchant(2)]
    db.execute.return_value.scalars.return_value.all.return_value = merchants

    result = MerchantContextService(db).list_accessible_merchants(_user("BRANCH_MANAGER"))

    assert [m.id for m in result] == [1, 2]


def test_resolve_active_merchant_uses_header_when_allowed():
    db = MagicMock()
    user = _user(active_merchant_id=1)
    service = MerchantContextService(db)
    service.list_accessible_merchants = MagicMock(return_value=[_merchant(1), _merchant(2)])
    service.user_can_access_merchant = MagicMock(side_effect=lambda _u, mid: mid in (1, 2))

    resolved = service.resolve_active_merchant_id(user, header_merchant_id=2, persist=False)

    assert resolved == 2


def test_resolve_active_merchant_requires_selection_when_multiple_and_none_set():
    db = MagicMock()
    user = _user(active_merchant_id=None)
    service = MerchantContextService(db)
    service.list_accessible_merchants = MagicMock(return_value=[_merchant(1), _merchant(2)])
    service.user_can_access_merchant = MagicMock(return_value=True)

    with pytest.raises(HTTPException) as exc:
        service.resolve_active_merchant_id(user, persist=False)

    assert exc.value.status_code == 400


def test_ensure_client_in_merchant_raises_when_mismatch():
    db = MagicMock()
    service = MerchantContextService(db)

    with pytest.raises(HTTPException) as exc:
        service.ensure_client_in_merchant(2, 1)

    assert exc.value.status_code == 404
