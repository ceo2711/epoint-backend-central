import base64
import hashlib
import hmac
from unittest.mock import MagicMock, patch

from app.services.client_email_inbox import (
    ingest_inbound_client_email,
    normalize_email,
    strip_quoted_reply,
)
from app.services.email.resend_inbound import (
    parse_resend_inbound_payload,
    verify_resend_webhook_signature,
)


def test_normalize_email_from_display_name():
    assert normalize_email("Alex Rivera <Demo.Client@Epoint.com>") == "demo.client@epoint.com"


def test_strip_quoted_reply_drops_original_message():
    body = "Necesito ayuda con el portal.\n\nOn Mon, Staff wrote:\n> Hola Alex"
    assert strip_quoted_reply(body) == "Necesito ayuda con el portal."


def test_strip_quoted_reply_drops_quoted_lines():
    body = "Listo, gracias.\n> El martes te escribí\n> otro renglón"
    assert strip_quoted_reply(body) == "Listo, gracias."


def test_parse_fixture_payload():
    parsed = parse_resend_inbound_payload(
        {
            "from": "Alex <alex@example.com>",
            "to": ["soporte@epointsolution.com"],
            "subject": "Re: Bienvenida",
            "text": "Hola equipo",
            "html": "<p>Hola equipo</p>",
            "email_id": "re_fixture_1",
        }
    )
    assert parsed["from_email"] == "alex@example.com"
    assert parsed["to_emails"] == ["soporte@epointsolution.com"]
    assert parsed["subject"] == "Re: Bienvenida"
    assert parsed["text"] == "Hola equipo"
    assert parsed["resend_email_id"] == "re_fixture_1"


def test_parse_resend_event_payload():
    parsed = parse_resend_inbound_payload(
        {
            "type": "email.received",
            "data": {
                "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
                "from": "steve.jobs@example.com",
                "to": ["inbound@epointsolution.com"],
                "subject": "Hello",
            },
        }
    )
    assert parsed["from_email"] == "steve.jobs@example.com"
    assert parsed["resend_email_id"] == "56761188-7520-42d8-8898-ff6fc54ce618"
    assert parsed["text"] == ""


def test_sync_receiving_inbox_skips_without_api_key(monkeypatch):
    from app.services.email.resend_inbound import sync_receiving_inbox

    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("RESEND_INBOUND_SYNC", "true")
    assert sync_receiving_inbox(MagicMock()) == 0


def test_verify_signature_skips_when_secret_empty():
    assert verify_resend_webhook_signature(b"{}", {}, "") is True


def test_verify_signature_rejects_missing_headers():
    assert verify_resend_webhook_signature(b"{}", {}, "whsec_dGVzdA==") is False


def test_verify_signature_accepts_valid_v1():
    secret_bytes = b"test-secret"
    secret = "whsec_" + base64.b64encode(secret_bytes).decode()
    body = b'{"ok":true}'
    msg_id = "msg_1"
    timestamp = "1710000000"
    signed = f"{msg_id}.{timestamp}.{body.decode()}".encode()
    digest = hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    assert (
        verify_resend_webhook_signature(
            body,
            {
                "svix-id": msg_id,
                "svix-timestamp": timestamp,
                "svix-signature": f"v1,{signature}",
            },
            secret,
        )
        is True
    )


def test_ingest_returns_existing_row_by_resend_id():
    existing = MagicMock()
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = existing

    result = ingest_inbound_client_email(
        db,
        from_email="alex@example.com",
        subject="Re: Hola",
        text="Hola",
        html_body=None,
        resend_email_id="re_dup",
    )

    assert result is existing
    db.add.assert_not_called()


def test_ingest_unknown_sender_returns_none():
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = None

    result = ingest_inbound_client_email(
        db,
        from_email="unknown@example.com",
        subject="Hola",
        text="Hola",
        html_body=None,
        resend_email_id=None,
    )

    assert result is None
    db.add.assert_not_called()


@patch("app.services.client_email_inbox.NotificationService")
@patch("app.services.clients.ClientService")
def test_ingest_creates_inbound_and_notifies(mock_client_service_cls, mock_notify_cls):
    advisor = MagicMock(id=11, is_active=True)
    onboarding = MagicMock(id=22, is_active=True)
    client = MagicMock(id=7, first_name="Alex", last_name="Rivera")
    client.assignments = []

    existing_q = MagicMock()
    existing_q.scalar_one_or_none.return_value = None
    client_q = MagicMock()
    client_q.unique.return_value.scalar_one_or_none.return_value = client
    db = MagicMock()
    db.execute.side_effect = [existing_q, client_q]

    service = mock_client_service_cls.return_value
    service._get_active_advisors.return_value = [advisor]
    service._get_mentionable_onboarding.return_value = [onboarding]

    result = ingest_inbound_client_email(
        db,
        from_email="alex@example.com",
        subject="Re: Portal",
        text="Necesito ayuda",
        html_body=None,
        resend_email_id="re_new",
        to_emails=["soporte@epointsolution.com"],
    )

    assert result is not None
    db.add.assert_called_once()
    created = db.add.call_args[0][0]
    assert created.direction == "INBOUND"
    assert created.client_id == 7
    assert created.from_email == "alex@example.com"
    assert created.sent_by_user_id is None
    mock_notify_cls.return_value.notify.assert_called_once()
    kwargs = mock_notify_cls.return_value.notify.call_args.kwargs
    assert kwargs["event_type"] == "CLIENT_EMAIL_RECEIVED"
    assert [user.id for user in kwargs["users"]] == [11, 22]
