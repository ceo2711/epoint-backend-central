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
    assert payload[0]["data"]["client_id"] == 7
