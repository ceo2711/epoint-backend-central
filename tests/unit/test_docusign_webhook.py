import base64
import hashlib
import hmac
import json

from app.services.docusign.webhook import (
    parse_connect_payload,
    verify_connect_signature,
)


def test_verify_connect_signature_valid():
    secret = "test-secret"
    body = b'{"event":"envelope-completed"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    assert verify_connect_signature(body, signature, secret, allow_missing=False) is True


def test_parse_connect_json_event():
    body = json.dumps(
        {
            "event": "envelope-completed",
            "data": {"envelopeId": "abc-123", "envelopeSummary": {"status": "completed"}},
        }
    ).encode()
    event = parse_connect_payload(body, "application/json")
    assert event is not None
    assert event.envelope_id == "abc-123"
    assert event.status == "completed"


def test_parse_connect_signed_status_as_completed():
    body = json.dumps(
        {
            "event": "envelope-completed",
            "data": {"envelopeId": "abc-123", "envelopeSummary": {"status": "signed"}},
        }
    ).encode()
    event = parse_connect_payload(body, "application/json")
    assert event is not None
    assert event.status == "completed"


def test_parse_connect_recipient_completed_event():
    body = json.dumps(
        {
            "event": "recipient-completed",
            "data": {"envelopeId": "abc-123"},
        }
    ).encode()
    event = parse_connect_payload(body, "application/json")
    assert event is not None
    assert event.envelope_id == "abc-123"
    assert event.status == "completed"


def test_parse_connect_recipient_completed_overrides_delivered_summary():
    body = json.dumps(
        {
            "event": "recipient-completed",
            "data": {
                "envelopeId": "abc-123",
                "envelopeSummary": {"status": "delivered"},
            },
        }
    ).encode()
    event = parse_connect_payload(body, "application/json")
    assert event is not None
    assert event.status == "completed"
