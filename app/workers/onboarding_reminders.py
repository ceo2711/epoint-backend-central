"""Worker de recordatorios recurrentes de onboarding incompleto."""

import logging
import threading

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.onboarding_reminders import run_onboarding_reminders
from app.workers.reminder_job_lock import release_reminder_job_lock, try_acquire_reminder_job_lock

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()


def run_onboarding_reminders_job() -> dict:
    if not _job_lock.acquire(blocking=False):
        logger.info("Ciclo de recordatorios omitido: ya hay uno en ejecución en este proceso")
        return _skipped_summary(skipped_concurrent=True)

    db = SessionLocal()
    lock_acquired = False
    try:
        lock_acquired = try_acquire_reminder_job_lock(db)
        if not lock_acquired:
            return _skipped_summary(skipped_concurrent=True)

        return run_onboarding_reminders(db)
    except Exception:
        logger.exception("Fallo crítico en recordatorios de onboarding")
        raise
    finally:
        if lock_acquired:
            release_reminder_job_lock(db)
        db.close()
        _job_lock.release()


def _skipped_summary(*, skipped_concurrent: bool) -> dict:
    return {
        "processed": 0,
        "sent": 0,
        "skipped": 0,
        "skipped_cooldown": 0,
        "failed": 0,
        "dry_run": get_settings().notifications_dry_run,
        "skipped_concurrent": skipped_concurrent,
    }
