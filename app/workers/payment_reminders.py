"""Worker de recordatorios de saldo de pago."""

import logging
import threading

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.payment_reminders import run_payment_reminders

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()


def run_payment_reminders_job(stop_event: threading.Event | None = None) -> dict:
    if stop_event is not None and stop_event.is_set():
        return _skipped_summary()

    if not _job_lock.acquire(blocking=False):
        logger.info("Ciclo de recordatorios de pago omitido: ya hay uno en este proceso")
        return _skipped_summary()

    if stop_event is not None and stop_event.is_set():
        _job_lock.release()
        return _skipped_summary()

    db = SessionLocal()
    try:
        return run_payment_reminders(db)
    except Exception:
        logger.exception("Fallo crítico en recordatorios de pago")
        raise
    finally:
        db.close()
        _job_lock.release()


def _skipped_summary() -> dict:
    return {
        "processed": 0,
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": get_settings().notifications_dry_run,
        "skipped_concurrent": True,
    }
