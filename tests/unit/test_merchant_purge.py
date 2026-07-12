"""Tests for merchant purge service."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.merchants import MerchantService


def _merchant(merchant_id: int = 1):
    merchant = MagicMock()
    merchant.id = merchant_id
    return merchant


def test_purge_merchant_not_found():
    db = MagicMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        MerchantService(db).purge_merchant(99)

    assert exc.value.status_code == 404


def test_purge_merchant_blocked_when_clients_exist():
    db = MagicMock()
    db.get.return_value = _merchant()
    db.execute.return_value.scalar_one.return_value = 2

    with pytest.raises(HTTPException) as exc:
        MerchantService(db).purge_merchant(1)

    assert exc.value.status_code == 409
    assert "2 cliente" in exc.value.detail


def test_purge_merchant_success():
    db = MagicMock()
    db.get.return_value = _merchant()
    db.execute.return_value.scalar_one.return_value = 0

    MerchantService(db).purge_merchant(1)

    db.delete.assert_called_once()
    db.commit.assert_called_once()
