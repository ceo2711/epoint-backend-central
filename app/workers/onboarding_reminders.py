"""Worker de recordatorios recurrentes de onboarding incompleto."""

import logging
import threading

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.onboarding_reminders import run_onboarding_reminders

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()


def run_onboarding_reminders_job() -> dict:
    if not _job_lock.acquire(blocking=False):
        logger.info("Ciclo de recordatorios omitido: ya hay uno en ejecución")
        return {
            "processed": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "dry_run": get_settings().notifications_dry_run,
            "skipped_concurrent": True,
        }

    db = SessionLocal()
    try:
        return run_onboarding_reminders(db)
    except Exception:
        logger.exception("Fallo crítico en recordatorios de onboarding")
        raise
    finally:
        db.close()
        _job_lock.release()
