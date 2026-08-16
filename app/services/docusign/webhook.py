"""Parser y validación HMAC para DocuSign Connect."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocusignConnectEvent:
    envelope_id: str
    status: str
    event_type: str


def verify_connect_signature(body: bytes, signature: str | None, secret: str, *, allow_missing: bool) -> bool:
    secret = secret.strip()
    if not secret:
        return allow_missing
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected.strip(), signature.strip())


DOCUSIGN_COMPLETED_ALIASES = frozenset({"completed", "signed"})


def normalize_docusign_status(status: str) -> str:
    """DocuSign a veces manda `signed` antes de `completed`; para el CRM es lo mismo."""
    lowered = (status or "").strip().lower()
    if lowered in DOCUSIGN_COMPLETED_ALIASES:
        return "completed"
    return lowered


def _status_from_event_type(event_type: str) -> str | None:
    mapping = {
        "envelope-sent": "sent",
        "envelope-delivered": "delivered",
        "envelope-completed": "completed",
        "envelope-declined": "declined",
        "envelope-voided": "voided",
        "recipient-completed": "completed",
        "recipient-signed": "completed",
        "recipient-declined": "declined",
    }
    mapped = mapping.get(event_type.lower())
    return normalize_docusign_status(mapped) if mapped else None


def _parse_json_event(payload: dict) -> DocusignConnectEvent | None:
    event_type = str(payload.get("event") or "").strip()
    data = payload.get("data") or {}
    envelope_id = (
        data.get("envelopeId")
        or (data.get("envelopeSummary") or {}).get("envelopeId")
        or payload.get("envelopeId")
    )
    if not envelope_id:
        return None

    summary = data.get("envelopeSummary") or {}
    status = str(summary.get("status") or data.get("status") or "").strip().lower()
    from_event = _status_from_event_type(event_type)
    if from_event == "completed":
        status = "completed"
    elif not status:
        status = from_event or ""
    else:
        status = normalize_docusign_status(status)
    if not status:
        return None

    return DocusignConnectEvent(
        envelope_id=str(envelope_id),
        status=status,
        event_type=event_type or status,
    )


def _parse_xml_event(body: bytes) -> DocusignConnectEvent | None:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None

    envelope_id = None
    status = None
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "EnvelopeID" and elem.text:
            envelope_id = elem.text.strip()
        if tag == "Status" and elem.text and status is None:
            status = elem.text.strip().lower()

    if not envelope_id or not status:
        return None

    status = normalize_docusign_status(status)
    return DocusignConnectEvent(
        envelope_id=envelope_id,
        status=status,
        event_type=f"envelope-{status}",
    )


def parse_connect_payload(body: bytes, content_type: str | None) -> DocusignConnectEvent | None:
    if not body:
        return None

    lowered = (content_type or "").lower()
    if "json" in lowered or body[:1] == b"{":
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("DocuSign Connect: payload JSON inválido")
            return None
        if isinstance(payload, dict):
            return _parse_json_event(payload)
        return None

    if "xml" in lowered or body[:1] == b"<":
        return _parse_xml_event(body)

    try:
        payload = json.loads(body.decode("utf-8"))
        if isinstance(payload, dict):
            return _parse_json_event(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    return _parse_xml_event(body)
