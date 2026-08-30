from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.payment_link import PaymentLinkStatus
from app.services.payment_reminders import run_payment_reminders
from app.services.payments.amounts import (
    STANDARD_INITIAL_PAYMENT,
    is_payment_satisfied,
    remaining_amount,
    remaining_to_standard,
)
from app.services.payments.service import PaymentService
from app.services.prospects import ProspectService


def _link(**kwargs):
    defaults = {
        "amount": Decimal("3000.00"),
        "amount_paid": Decimal("0.00"),
        "status": PaymentLinkStatus.PENDING.value,
        "allow_partial": True,
        "currency": "USD",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_remaining_amount_after_partial():
    link = _link(amount_paid=Decimal("1000.00"))
    assert remaining_amount(link) == Decimal("2000.00")


def test_payment_satisfied_when_partial():
    assert is_payment_satisfied(_link(status=PaymentLinkStatus.PARTIAL.value, amount_paid=Decimal("500")))
    assert not is_payment_satisfied(_link(status=PaymentLinkStatus.PENDING.value))


def test_ready_for_conversion_accepts_partial_payment():
    svc = ProspectService.__new__(ProspectService)
    svc.db = MagicMock()
    svc.db.get.return_value = _link(
        status=PaymentLinkStatus.PARTIAL.value,
        amount_paid=Decimal("1000.00"),
    )
    svc._seller_marked_contacted = MagicMock(return_value=True)
    svc.list_linked_envelopes = MagicMock(return_value=[SimpleNamespace(status="completed")])
    prospect = SimpleNamespace(
        status="PAGO_PARCIAL",
        payment_link_id=10,
    )
    assert svc._ready_for_conversion(prospect) is True


def test_status_from_payments_is_partial_below_standard():
    svc = ProspectService.__new__(ProspectService)
    svc.list_linked_payment_links = MagicMock(
        return_value=[
            _link(amount=Decimal("30.00"), amount_paid=Decimal("30.00"), status="paid"),
        ]
    )
    assert svc._status_from_payments(SimpleNamespace()) == "PAGO_PARCIAL"


def test_status_from_payments_is_completed_at_standard():
    svc = ProspectService.__new__(ProspectService)
    svc.list_linked_payment_links = MagicMock(
        return_value=[
            _link(amount=Decimal("30.00"), amount_paid=Decimal("30.00"), status="paid"),
            _link(amount=Decimal("2970.00"), amount_paid=Decimal("2970.00"), status="paid"),
        ]
    )
    assert svc._status_from_payments(SimpleNamespace()) == "PAGO_COMPLETADO"


def test_payment_reminders_skip_within_cooldown():
    from datetime import datetime, timedelta, timezone

    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    link = _link(
        customer_email="ana@example.com",
        customer_first_name="Ana",
        payment_url="https://example.com/pay",
        last_payment_reminder_at=recent,
        description=None,
        provider="authorize",
        id=7,
        status=PaymentLinkStatus.PARTIAL.value,
        amount_paid=Decimal("1000"),
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_payment_reminders_skip_recently_created_link():
    from datetime import datetime, timedelta, timezone

    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    link = _link(
        customer_email="ana@example.com",
        customer_first_name="Ana",
        payment_url="https://example.com/pay",
        last_payment_reminder_at=None,
        created_at=recent,
        description=None,
        provider="authorize",
        id=8,
        status=PaymentLinkStatus.PENDING.value,
        amount_paid=Decimal("0"),
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_normalize_full_payment_is_always_3000():
    assert PaymentService.normalize_create_amount(
        allow_partial=False, amount=Decimal("500.00")
    ) == STANDARD_INITIAL_PAYMENT


def test_normalize_partial_accepts_smaller_amount():
    assert PaymentService.normalize_create_amount(
        allow_partial=True, amount=Decimal("1000.00")
    ) == Decimal("1000.00")


def test_normalize_partial_rejects_standard_or_more():
    with pytest.raises(HTTPException) as exc:
        PaymentService.normalize_create_amount(allow_partial=True, amount=Decimal("3000.00"))
    assert exc.value.status_code == 400


def test_remaining_to_standard_after_partial_paid():
    leftover = remaining_to_standard(
        [
            _link(amount=Decimal("1000.00"), amount_paid=Decimal("1000.00"), status="paid"),
        ]
    )
    assert leftover == Decimal("2000.00")


def test_remaining_to_standard_is_zero_when_covered():
    leftover = remaining_to_standard(
        [
            _link(amount_paid=Decimal("3000.00"), status="paid"),
        ]
    )
    assert leftover == Decimal("0.00")
