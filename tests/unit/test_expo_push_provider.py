from unittest.mock import MagicMock, patch

from app.services.notifications.providers import ExpoPushProvider


def test_expo_push_provider_returns_false_without_tokens():
    assert ExpoPushProvider().send_to_tokens([], "t", "b") is False


@patch("httpx.Client")
def test_expo_push_provider_posts_messages(mock_client_cls):
    client = MagicMock()
    response = MagicMock()
    response.status_code = 200
    client.post.return_value = response
    mock_client_cls.return_value.__enter__.return_value = client

    ok = ExpoPushProvider().send_to_tokens(
        ["ExponentPushToken[abc]"],
        "Nuevo comentario",
        "Revisá la tarea",
        {"client_id": 7, "card_id": 3},
    )

    assert ok is True
    client.post.assert_called_once()
    _, kwargs = client.post.call_args
    payload = kwargs["json"]
    assert payload[0]["to"] == "ExponentPushToken[abc]"
    assert payload[0]["title"] == "Nuevo comentario"
    assert payload[0]["priority"] == "high"
    assert payload[0]["channelId"] == "epoint-default"
    assert payload[0]["data"]["client_id"] == "7"
    assert payload[0]["data"]["card_id"] == "3"


def test_serialize_expo_push_data_skips_nulls_and_stringifies():
    from app.services.notifications.providers import serialize_expo_push_data

    assert serialize_expo_push_data(
        {"client_id": 9, "prospect_id": None, "ok": True, "event_type": "PAYMENT_LINK_COMPLETED"}
    ) == {
        "client_id": "9",
        "ok": "true",
        "event_type": "PAYMENT_LINK_COMPLETED",
    }


def test_sales_funnel_events_include_push():
    from app.services.notifications.service import EVENT_CHANNELS

    for event in (
        "DOCUSIGN_ENVELOPE_COMPLETED",
        "PAYMENT_LINK_COMPLETED",
        "PROSPECT_CONVERTED",
        "CALENDLY_EVENT_SCHEDULED",
    ):
        assert "PUSH" in EVENT_CHANNELS[event]
        assert "IN_APP" in EVENT_CHANNELS[event]
