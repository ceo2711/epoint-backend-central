from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.sub_sellers import (
    ELIGIBILITY_WINDOW_MONTHS,
    MIN_MONTHLY_SALES,
    MIN_PREVIOUS_MONTH_SALES,
    SubSellerService,
    eligibility_window_months,
    previous_calendar_month_bounds,
    shift_calendar_month,
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


def test_eligibility_window_includes_current_and_two_previous():
    window = eligibility_window_months(now=datetime(2026, 8, 2, tzinfo=timezone.utc))
    assert len(window) == ELIGIBILITY_WINDOW_MONTHS
    assert [(y, m) for y, m, *_ in window] == [(2026, 8), (2026, 7), (2026, 6)]


def test_shift_calendar_month_across_year():
    assert shift_calendar_month(2026, 1, delta=-1) == (2025, 12)
    assert shift_calendar_month(2025, 12, delta=1) == (2026, 1)


def test_eligibility_requires_at_least_five_in_any_window_month(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    user = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None)
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)

    # Los 3 meses de la ventana < 5 → no elegible.
    monkeypatch.setattr(service, "count_concretized_sales", lambda *a, **k: 4)
    assert service.eligibility(user, now=now)["eligible"] is False

    # Solo el mes -2 (junio) califica → elegible (renueva la ventana).
    def count_june_qualified(_uid, *, start, end_exclusive):
        if start.year == 2026 and start.month == 6:
            return 5
        return 0

    monkeypatch.setattr(service, "count_concretized_sales", count_june_qualified)
    result = service.eligibility(user, now=now)
    assert result["eligible"] is True
    assert result["can_manage_sub_sellers"] is True
    assert result["required_sales"] == MIN_MONTHLY_SALES == MIN_PREVIOUS_MONTH_SALES
    assert result["window_months"] == 3
    assert result["qualifying_months"] == 1
    assert result["consecutive_months_below_threshold"] == 2


def test_eligibility_lost_after_three_consecutive_months_below(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    user = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None)
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)

    # Ago/Jul/Jun < 5, pero mayo (fuera de ventana) tenía 10 → no cuenta.
    def count_only_may(_uid, *, start, end_exclusive):
        if start.year == 2026 and start.month == 5:
            return 10
        return 2

    monkeypatch.setattr(service, "count_concretized_sales", count_only_may)
    result = service.eligibility(user, now=now)
    assert result["eligible"] is False
    assert result["consecutive_months_below_threshold"] == 3


def test_sub_seller_never_eligible(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    legacy = SimpleNamespace(id=2, role=SimpleNamespace(code="SALES_REP"), parent_user_id=9)
    modern = SimpleNamespace(id=3, role=SimpleNamespace(code="SUB_SELLER"), parent_user_id=9)
    monkeypatch.setattr(service, "count_concretized_sales", lambda *a, **k: 99)
    assert service.eligibility(legacy)["eligible"] is False
    assert service.eligibility(legacy)["is_sub_seller"] is True
    assert service.eligibility(modern)["eligible"] is False
    assert service.eligibility(modern)["is_sub_seller"] is True


def test_deactivate_active_sub_sellers_marks_inactive_and_revokes(monkeypatch):
    from types import SimpleNamespace

    service = SubSellerService(db=MagicMock())
    parent = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None)
    sub = SimpleNamespace(id=10, is_active=True, parent_user_id=1)
    session = SimpleNamespace(user_id=10, is_revoked=False)

    service.db.execute.side_effect = [
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [sub])),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [session])),
    ]

    n = service.deactivate_active_sub_sellers(parent, commit=True)
    assert n == 1
    assert sub.is_active is False
    assert session.is_revoked is True
    service.db.commit.assert_called()


def test_assert_sub_seller_may_login_blocks_when_parent_ineligible(monkeypatch):
    service = SubSellerService(db=MagicMock())
    sub = SimpleNamespace(
        id=10,
        is_active=True,
        parent_user_id=1,
        role=SimpleNamespace(code="SUB_SELLER"),
    )
    parent = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None)

    service.db.execute.return_value = SimpleNamespace(
        unique=lambda: SimpleNamespace(scalar_one_or_none=lambda: parent)
    )
    monkeypatch.setattr(service, "can_manage_sub_sellers", lambda _u: False)
    monkeypatch.setattr(service, "deactivate_active_sub_sellers", lambda *_a, **_k: 1)

    with pytest.raises(HTTPException) as exc:
        service.assert_sub_seller_may_login(sub)
    assert exc.value.status_code == 403
    assert "desactivada" in exc.value.detail.lower()


def test_assert_sub_seller_may_login_blocks_inactive_even_if_parent_ok(monkeypatch):
    service = SubSellerService(db=MagicMock())
    sub = SimpleNamespace(
        id=10,
        is_active=False,
        parent_user_id=1,
        role=SimpleNamespace(code="SUB_SELLER"),
    )
    parent = SimpleNamespace(id=1, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None)
    service.db.execute.return_value = SimpleNamespace(
        unique=lambda: SimpleNamespace(scalar_one_or_none=lambda: parent)
    )
    monkeypatch.setattr(service, "can_manage_sub_sellers", lambda _u: True)

    with pytest.raises(HTTPException) as exc:
        service.assert_sub_seller_may_login(sub)
    assert "desactivada" in exc.value.detail.lower()


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


def test_reassign_requires_supervise_permission(monkeypatch):
    service = SubSellerService(db=SimpleNamespace())
    actor = SimpleNamespace(id=99, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None, area=None)
    with pytest.raises(HTTPException) as exc:
        service.reassign_sub_seller(actor, 10, new_parent_user_id=2)
    assert exc.value.status_code == 403


def test_set_sales_staff_active_requires_supervise():
    service = SubSellerService(db=SimpleNamespace())
    actor = SimpleNamespace(id=99, role=SimpleNamespace(code="SALES_REP"), parent_user_id=None, area=None)
    with pytest.raises(HTTPException) as exc:
        service.set_sales_staff_active(actor, 10, is_active=False)
    assert exc.value.status_code == 403


def test_set_sales_staff_active_blocks_self():
    service = SubSellerService(db=SimpleNamespace())
    actor = SimpleNamespace(
        id=7,
        role=SimpleNamespace(code="AREA_LEADER"),
        area=SimpleNamespace(code="VENTAS"),
        parent_user_id=None,
    )
    with pytest.raises(HTTPException) as exc:
        service.set_sales_staff_active(actor, 7, is_active=False)
    assert exc.value.status_code == 400
