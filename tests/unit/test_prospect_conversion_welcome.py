from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.prospects import ProspectService


@patch("app.services.prospects.send_client_conversion_welcome_email", return_value=True)
def test_conversion_welcome_is_sent_and_marked_once(mock_send: MagicMock):
    service = ProspectService.__new__(ProspectService)
    service.db = MagicMock()
    service.db.get.return_value = SimpleNamespace(name="Comercio Demo")
    client = SimpleNamespace(
        id=10,
        first_name="María",
        email="cliente@ejemplo.com",
        merchant_id=3,
        conversion_welcome_email_sent_at=None,
    )
    link = SimpleNamespace(amount=Decimal("150.00"), currency="USD")

    service._send_client_conversion_welcome(client, link)
    service._send_client_conversion_welcome(client, link)

    assert client.conversion_welcome_email_sent_at is not None
    mock_send.assert_called_once()
    service.db.commit.assert_called_once()


@patch("app.services.prospects.send_client_conversion_welcome_email", return_value=False)
def test_conversion_succeeds_when_welcome_delivery_fails(mock_send: MagicMock):
    service = ProspectService.__new__(ProspectService)
    service.db = MagicMock()
    service.db.get.return_value = None
    client = SimpleNamespace(
        id=10,
        first_name="María",
        email="cliente@ejemplo.com",
        merchant_id=None,
        conversion_welcome_email_sent_at=None,
    )
    link = SimpleNamespace(amount=Decimal("150.00"), currency="USD")

    service._send_client_conversion_welcome(client, link)

    assert client.conversion_welcome_email_sent_at is None
    mock_send.assert_called_once()
    service.db.commit.assert_not_called()
