from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.sub_sellers import (
    MIN_PREVIOUS_MONTH_SALES,
    SubSellerService,
    previous_calendar_month_bounds,
)


def test_previous_calendar_month_bounds_january():
    start, end, year, month = previous_calendar_month_bounds(
        now=datetime(2026, 1, 15, tzinfo=timezone.utc)
    )
    assert year == 2025
    assert month == 12
    assert start == datetime(2025, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_previous_calendar_month_bounds_mid_year():
    start, end, year, month = previous_calendar_month_bounds(
        now=datetime(2026, 7, 25, tzinfo=timezone.utc)
    )
    assert (year, month) == (2026, 6)
    assert start == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_eligibility_requires_at_least_five(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    user = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None)

    monkeypatch.setattr(service, "count_concretized_sales", lambda *a, **k: 4)
    assert service.eligibility(user)["eligible"] is False

    monkeypatch.setattr(service, "count_concretized_sales", lambda *a, **k: 5)
    result = service.eligibility(user)
    assert result["eligible"] is True
    assert result["can_manage_sub_sellers"] is True
    assert result["required_sales"] == MIN_PREVIOUS_MONTH_SALES
    assert result["threshold_exclusive"] is False


def test_sub_seller_never_eligible(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    user = SimpleNamespace(id=2, role=SimpleNamespace(code="SALES_REP"), parent_user_id=9)
    monkeypatch.setattr(service, "count_concretized_sales", lambda *a, **k: 99)
    assert service.eligibility(user)["eligible"] is False
    assert service.eligibility(user)["is_sub_seller"] is True


def test_create_blocked_when_not_eligible(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    parent = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None, sede_id=1)
    monkeypatch.setattr(service, "can_manage_sub_sellers", lambda _u: False)

    with pytest.raises(HTTPException) as exc:
        service.create_sub_seller(
            parent,
            email="sub@epoint.com",
            password="password1",
            first_name="Sub",
            last_name="Seller",
        )
    assert exc.value.status_code == 403
