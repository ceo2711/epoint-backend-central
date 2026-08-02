"""Desactiva subvendedores cuando el vendedor titular pierde elegibilidad."""

from __future__ import annotations

import logging
import threading

from app.core.database import SessionLocal
from app.services.sub_sellers import SubSellerService

logger = logging.getLogger(__name__)


def run_sub_seller_eligibility_enforcement_job(
    stop_event: threading.Event | None = None,
) -> dict:
    if stop_event is not None and stop_event.is_set():
        return {"skipped": True, "reason": "stop_requested"}

    db = SessionLocal()
    try:
        result = SubSellerService(db).enforce_all_ineligible_parents()
        logger.info(
            "Enforcement elegibilidad subvendedores: %s",
            result,
        )
        return result
    finally:
        db.close()
