from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.payment_link import PaymentLinkStatus
from app.schemas.payment import (
    PaymentLinkCreate,
    PaymentLinkRemainderDueUpdate,
    registration_calendar_today,
)
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
        "remainder_due_on": None,
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
        remainder_due_on=date.today() - timedelta(days=1),
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_payment_reminders_skip_recently_created_link():
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
        remainder_due_on=None,
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_payment_reminders_skip_non_shareable_url():
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    link = _remindable_partial(
        payment_url="migration",
        last_payment_reminder_at=old,
        created_at=old,
        remainder_due_on=date.today() - timedelta(days=1),
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def _remindable_partial(**kwargs):
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    defaults = {
        "customer_email": "ana@example.com",
        "customer_first_name": "Ana",
        "payment_url": "https://example.com/pay",
        "last_payment_reminder_at": old,
        "created_at": old,
        "description": None,
        "provider": "authorize",
        "id": 11,
        "status": PaymentLinkStatus.PARTIAL.value,
        "amount_paid": Decimal("1000"),
        "remainder_due_on": None,
    }
    defaults.update(kwargs)
    return _link(**defaults)


def test_payment_reminders_skip_partial_without_due_date():
    link = _remindable_partial()
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_payment_reminders_skip_partial_before_due_date():
    link = _remindable_partial(remainder_due_on=date.today() + timedelta(days=20))
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["sent"] == 0


def test_payment_reminders_send_partial_after_due_date():
    link = _remindable_partial(remainder_due_on=date.today() - timedelta(days=1))
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email", return_value=True) as send:
        summary = run_payment_reminders(db)

    send.assert_called_once()
    assert summary["sent"] == 1


def test_payment_reminders_skip_balance_link_before_due_date():
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    link = _link(
        customer_email="ana@example.com",
        customer_first_name="Ana",
        payment_url="https://example.com/pay",
        last_payment_reminder_at=None,
        created_at=old,
        description=None,
        provider="authorize",
        id=12,
        status=PaymentLinkStatus.PENDING.value,
        amount_paid=Decimal("0"),
        allow_partial=False,
        remainder_due_on=date.today() + timedelta(days=10),
        amount=Decimal("2000.00"),
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email") as send:
        summary = run_payment_reminders(db)

    send.assert_not_called()
    assert summary["skipped"] == 1


def test_payment_reminders_send_first_pending_after_cooldown():
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    link = _link(
        customer_email="ana@example.com",
        customer_first_name="Ana",
        payment_url="https://example.com/pay",
        last_payment_reminder_at=None,
        created_at=old,
        description=None,
        provider="authorize",
        id=13,
        status=PaymentLinkStatus.PENDING.value,
        amount_paid=Decimal("0"),
        remainder_due_on=date.today() + timedelta(days=20),
        allow_partial=True,
    )
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    with patch("app.services.payment_reminders.send_payment_reminder_email", return_value=True) as send:
        summary = run_payment_reminders(db)

    send.assert_called_once()
    assert summary["sent"] == 1


def test_partial_create_requires_remainder_due_on():
    with pytest.raises(ValidationError):
        PaymentLinkCreate(
            customer_first_name="Ana",
            customer_last_name="Lopez",
            customer_email="ana@example.com",
            customer_phone="5551234567",
            amount=Decimal("1000.00"),
            provider="authorize",
            allow_partial=True,
        )


def test_remainder_due_update_rejects_past_date():
    yesterday = registration_calendar_today() - timedelta(days=1)
    with pytest.raises(ValidationError):
        PaymentLinkRemainderDueUpdate(remainder_due_on=yesterday)


def test_remainder_due_update_accepts_today():
    today = registration_calendar_today()
    payload = PaymentLinkRemainderDueUpdate(remainder_due_on=today)
    assert payload.remainder_due_on == today


def test_partial_create_rejects_past_remainder_due_on():
    with pytest.raises(ValidationError):
        PaymentLinkCreate(
            customer_first_name="Ana",
            customer_last_name="Lopez",
            customer_email="ana@example.com",
            customer_phone="5551234567",
            amount=Decimal("1000.00"),
            provider="authorize",
            allow_partial=True,
            remainder_due_on=registration_calendar_today() - timedelta(days=1),
        )


def test_update_remainder_due_rejects_cancelled_link():
    svc = PaymentService.__new__(PaymentService)
    svc.db = MagicMock()
    svc.ensure_access = MagicMock()
    svc._get_link_for_user = MagicMock(
        return_value=_link(status=PaymentLinkStatus.CANCELLED.value, prospect_id=None)
    )
    with pytest.raises(HTTPException) as exc:
        svc.update_remainder_due_on(
            user=MagicMock(),
            link_id=1,
            remainder_due_on=date.today() + timedelta(days=7),
            merchant_id=1,
        )
    assert exc.value.status_code == 400


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


def test_record_received_partial_keeps_balance_without_sending_link():
    from app.schemas.payment import PaymentLinkCreate

    user = SimpleNamespace(id=4, role=SimpleNamespace(code="SALES_REP"))
    payload = PaymentLinkCreate(
        customer_first_name="Ana",
        customer_last_name="Lopez",
        customer_email="ana@example.com",
        customer_phone="5551234567",
        amount=Decimal("1000.00"),
        provider="paypal",
        allow_partial=True,
        remainder_due_on=date.today() + timedelta(days=10),
        send_email=True,
    )
    svc = PaymentService(MagicMock())
    svc.ensure_access = MagicMock()
    captured: dict = {}

    def apply(link, charged=None):
        link.amount_paid = charged
        link.status = PaymentLinkStatus.PARTIAL.value
        captured["link"] = link
        captured["charged"] = charged

    svc._apply_received_payment = apply
    svc._to_response = lambda link: SimpleNamespace(
        status=link.status,
        amount=link.amount,
        amount_paid=link.amount_paid,
        remainder_due_on=link.remainder_due_on,
    )

    with (
        patch("app.services.payments.service.send_payment_link_email") as send_link,
        patch("app.services.payments.service.send_payment_reminder_email") as send_reminder,
        patch.object(PaymentService, "_create_provider_checkout") as checkout,
    ):
        result = svc.create_link(user, payload, merchant_id=1)

    send_link.assert_not_called()
    send_reminder.assert_not_called()
    checkout.assert_not_called()
    assert result.email_sent is False
    assert captured["charged"] == Decimal("1000.00")
    assert captured["link"].amount == STANDARD_INITIAL_PAYMENT
    assert captured["link"].provider == "paypal"
    assert captured["link"].remainder_due_on == payload.remainder_due_on
    assert captured["link"].payment_url.startswith("http")
    assert result.link.status == PaymentLinkStatus.PARTIAL.value


def test_record_received_full_payment_marks_standard_amount():
    from app.schemas.payment import PaymentLinkCreate

    user = SimpleNamespace(id=4, role=SimpleNamespace(code="SALES_REP"))
    payload = PaymentLinkCreate(
        customer_first_name="Ana",
        customer_last_name="Lopez",
        customer_email="ana@example.com",
        customer_phone="5551234567",
        amount=Decimal("3000.00"),
        provider="authorize",
    )
    svc = PaymentService(MagicMock())
    svc.ensure_access = MagicMock()
    captured: dict = {}

    def apply(link, charged=None):
        link.amount_paid = charged
        link.status = PaymentLinkStatus.PAID.value
        captured["link"] = link
        captured["charged"] = charged

    svc._apply_received_payment = apply
    svc._to_response = lambda link: SimpleNamespace(status=link.status, amount=link.amount)

    result = svc.create_link(user, payload, merchant_id=1)

    assert result.email_sent is False
    assert captured["charged"] == STANDARD_INITIAL_PAYMENT
    assert captured["link"].amount == STANDARD_INITIAL_PAYMENT
    assert captured["link"].remainder_due_on is None
    assert captured["link"].allow_partial is False


def test_record_received_rejects_amount_over_standard():
    from app.schemas.payment import PaymentLinkCreate

    user = SimpleNamespace(id=4, role=SimpleNamespace(code="SALES_REP"))
    payload = PaymentLinkCreate(
        customer_first_name="Ana",
        customer_last_name="Lopez",
        customer_email="ana@example.com",
        customer_phone="5551234567",
        amount=Decimal("3500.00"),
        provider="authorize",
    )
    svc = PaymentService(MagicMock())
    svc.ensure_access = MagicMock()
    with pytest.raises(HTTPException) as exc:
        svc.create_link(user, payload, merchant_id=1)
    assert exc.value.status_code == 400


def test_remaining_to_standard_is_zero_when_covered():
    leftover = remaining_to_standard(
        [
            _link(amount_paid=Decimal("3000.00"), status="paid"),
        ]
    )
    assert leftover == Decimal("0.00")
