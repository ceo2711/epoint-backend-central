"""Webhooks públicos (sin JWT)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DbSession
from app.core.config import get_settings
from app.services.client_email_inbox import ingest_inbound_client_email
from app.services.email.resend_inbound import (
    fetch_receiving_email_body,
    parse_resend_inbound_payload,
    verify_resend_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/resend/inbound")
async def resend_inbound_webhook(request: Request, db: DbSession) -> dict[str, Any]:
    """Recibe respuestas de clientes vía Resend inbound."""
    body = await request.body()
    settings = get_settings()
    if not verify_resend_webhook_signature(body, request.headers, settings.resend_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma inválida")

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        logger.info("Webhook inbound Resend con JSON inválido")
        return {"ok": True, "ingested": False}

    if not isinstance(payload, dict):
        return {"ok": True, "ingested": False}

    parsed = parse_resend_inbound_payload(payload)
    text = parsed["text"]
    html_body = parsed["html"] or None
    email_id = parsed["resend_email_id"]

    if not text and not html_body and email_id:
        fetched_text, fetched_html = fetch_receiving_email_body(email_id, settings)
        text = fetched_text
        html_body = fetched_html

    row = ingest_inbound_client_email(
        db,
        from_email=parsed["from_email"],
        subject=parsed["subject"],
        text=text,
        html_body=html_body,
        resend_email_id=email_id,
        to_emails=parsed["to_emails"],
    )
    return {"ok": True, "ingested": row is not None}
