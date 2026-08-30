"""Worker de recordatorios de contratos sin firmar."""

import logging
import threading

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.contract_reminders import run_contract_reminders

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()


def run_contract_reminders_job(stop_event: threading.Event | None = None) -> dict:
    if stop_event is not None and stop_event.is_set():
        return _skipped_summary()

    if not _job_lock.acquire(blocking=False):
        logger.info("Ciclo de recordatorios de contrato omitido: ya hay uno en este proceso")
        return _skipped_summary()

    if stop_event is not None and stop_event.is_set():
        _job_lock.release()
        return _skipped_summary()

    db = SessionLocal()
    try:
        return run_contract_reminders(db)
    except Exception:
        logger.exception("Fallo crítico en recordatorios de contrato")
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
