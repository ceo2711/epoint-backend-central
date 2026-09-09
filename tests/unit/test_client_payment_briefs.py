from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.payment_link import PaymentLinkStatus
from app.serializers.prospect_pipeline import list_client_payment_briefs, payment_brief
from app.services.payments.amounts import public_payment_url


def _link(**kwargs):
    defaults = {
        "id": 1,
        "amount": Decimal("3000.00"),
        "amount_paid": Decimal("1500.00"),
        "status": PaymentLinkStatus.PARTIAL.value,
        "allow_partial": True,
        "currency": "USD",
        "payment_url": "https://example.com/pay",
        "paid_at": None,
        "remainder_due_on": None,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_public_payment_url_keeps_http_links():
    assert public_payment_url("https://pay.example/abc") == "https://pay.example/abc"
    assert public_payment_url("http://localhost:3000/pay") == "http://localhost:3000/pay"


def test_public_payment_url_hides_migration_placeholder():
    assert public_payment_url("migration") == ""
    assert public_payment_url("  ") == ""
    assert public_payment_url(None) == ""


def test_payment_brief_sanitizes_non_http_url():
    brief = payment_brief(_link(payment_url="migration"))
    assert brief.payment_url == ""
    assert brief.status == PaymentLinkStatus.PARTIAL.value
    assert brief.remaining_amount == Decimal("1500.00")


def test_list_client_payment_briefs_loads_by_client_id():
    link = _link(id=42, payment_url="migration")
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [link]

    briefs = list_client_payment_briefs(db, 180)

    assert len(briefs) == 1
    assert briefs[0].id == 42
    assert briefs[0].payment_url == ""
    db.execute.assert_called_once()
