from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.users import _assert_unique_active_area_leader


def _role(code: str = "AREA_LEADER"):
    return SimpleNamespace(code=code)


def test_skips_non_area_leader():
    db = MagicMock()
    _assert_unique_active_area_leader(
        db, role=_role("SALES_REP"), area_id=1, sede_id=1, is_active=True
    )
    db.execute.assert_not_called()


def test_skips_inactive():
    db = MagicMock()
    _assert_unique_active_area_leader(
        db, role=_role(), area_id=1, sede_id=1, is_active=False
    )
    db.execute.assert_not_called()


def test_allows_when_no_existing_leader():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    _assert_unique_active_area_leader(
        db, role=_role(), area_id=1, sede_id=2, is_active=True
    )
    db.execute.assert_called_once()


def test_rejects_duplicate_active_leader():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(id=99)
    db.get.return_value = SimpleNamespace(name="Ventas")

    with pytest.raises(HTTPException) as exc:
        _assert_unique_active_area_leader(
            db,
            role=_role(),
            area_id=1,
            sede_id=2,
            is_active=True,
            exclude_user_id=7,
        )

    assert exc.value.status_code == 409
    assert "Ventas" in exc.value.detail
