"""Parseo y verificación del webhook inbound de Resend."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any, Mapping

from app.core.config import Settings, get_settings
from app.services.client_email_inbox import normalize_email

logger = logging.getLogger(__name__)


def verify_resend_webhook_signature(
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
) -> bool:
    """Valida la firma Svix de Resend. Si no hay secreto, acepta (local)."""
    secret = (secret or "").strip()
    if not secret:
        return True

    msg_id = _header(headers, "svix-id")
    timestamp = _header(headers, "svix-timestamp")
    signature_header = _header(headers, "svix-signature")
    if not msg_id or not timestamp or not signature_header:
        return False

    try:
        secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
    except Exception:
        logger.warning("RESEND_WEBHOOK_SECRET inválido")
        return False

    signed = f"{msg_id}.{timestamp}.{body.decode('utf-8')}".encode()
    digest = hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()

    for part in signature_header.split():
        version, _, value = part.partition(",")
        if version != "v1" or not value:
            continue
        if hmac.compare_digest(value, expected):
            return True
    return False


def parse_resend_inbound_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normaliza el evento oficial de Resend y el fixture local."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        data = payload

    from_raw = data.get("from") or payload.get("from")
    to_raw = data.get("to") or payload.get("to") or []
    subject = str(data.get("subject") or payload.get("subject") or "").strip()
    text = _first_str(data.get("text"), payload.get("text"))
    html_body = _first_str(data.get("html"), payload.get("html"))
    email_id = _first_str(
        data.get("email_id"),
        data.get("id") if data.get("object") == "email" else None,
        payload.get("email_id"),
    )

    return {
        "from_email": _extract_email(from_raw),
        "to_emails": _extract_email_list(to_raw),
        "subject": subject,
        "text": text,
        "html": html_body,
        "resend_email_id": email_id or None,
    }


def fetch_receiving_email_body(
    email_id: str,
    settings: Settings | None = None,
) -> tuple[str, str | None]:
    """GET /emails/receiving/{id} cuando el webhook no trae el cuerpo."""
    data = fetch_receiving_email(email_id, settings)
    if not data:
        return "", None
    return _first_str(data.get("text")), _first_str(data.get("html")) or None


def fetch_receiving_email(email_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    if not email_id or not settings.resend_api_key:
        return None
    return _resend_get(f"https://api.resend.com/emails/receiving/{email_id}", settings)


def list_receiving_emails(settings: Settings | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.resend_api_key:
        return []
    data = _resend_get(f"https://api.resend.com/emails/receiving?limit={limit}", settings)
    if not data:
        return []
    items = data.get("data")
    return items if isinstance(items, list) else []


def sync_receiving_inbox(db, settings: Settings | None = None, *, limit: int = 20) -> int:
    """Importa Receiving → hilo local. Para local/dev sin túnel de webhook."""
    from app.services.client_email_inbox import ingest_inbound_client_email

    settings = settings or get_settings()
    if not settings.resend_inbound_sync or not settings.resend_api_key:
        return 0
    ingested = 0
    for item in list_receiving_emails(settings, limit=limit):
        email_id = _first_str(item.get("id"), item.get("email_id"))
        detail = fetch_receiving_email(email_id, settings) if email_id else None
        source = detail or item
        parsed = parse_resend_inbound_payload(source)
        if email_id and not parsed["resend_email_id"]:
            parsed["resend_email_id"] = email_id
        text = parsed["text"]
        html_body = parsed["html"] or None
        if not text and not html_body and email_id and detail is None:
            continue
        row = ingest_inbound_client_email(
            db,
            from_email=parsed["from_email"],
            subject=parsed["subject"],
            text=text,
            html_body=html_body,
            resend_email_id=parsed["resend_email_id"],
            to_emails=parsed["to_emails"],
        )
        if row is not None:
            ingested += 1
    return ingested


def _resend_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "User-Agent": "epoint-crm/1.0",
    }


def _resend_get(url: str, settings: Settings) -> dict[str, Any] | None:
    try:
        import httpx

        response = httpx.get(url, headers=_resend_headers(settings), timeout=20)
        if response.status_code == 401:
            logger.warning(
                "RESEND_API_KEY no puede leer Receiving (suele ser 'Sending access'). "
                "Creá una key Full access en Resend → API keys."
            )
            return None
        if response.status_code >= 400:
            logger.warning("Resend Receiving HTTP %s en %s", response.status_code, url)
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception:
        logger.exception("Error consultando Resend Receiving")
        return None


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value or "").strip()
    return ""


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _extract_email(value: Any) -> str:
    if isinstance(value, dict):
        return normalize_email(str(value.get("email") or value.get("address") or ""))
    if isinstance(value, list) and value:
        return _extract_email(value[0])
    if isinstance(value, str):
        return normalize_email(value)
    return ""


def _extract_email_list(value: Any) -> list[str]:
    if isinstance(value, str):
        parsed = normalize_email(value)
        return [parsed] if parsed else []
    if isinstance(value, dict):
        parsed = _extract_email(value)
        return [parsed] if parsed else []
    if isinstance(value, list):
        emails: list[str] = []
        for item in value:
            parsed = _extract_email(item)
            if parsed:
                emails.append(parsed)
        return emails
    return []
