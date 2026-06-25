"""Worker de recordatorios recurrentes de onboarding incompleto."""

import logging

from app.core.database import SessionLocal
from app.services.onboarding_reminders import run_onboarding_reminders

logger = logging.getLogger(__name__)


def run_onboarding_reminders_job() -> dict:
    db = SessionLocal()
    try:
        return run_onboarding_reminders(db)
    except Exception:
        logger.exception("Fallo crítico en recordatorios de onboarding")
        raise
    finally:
        db.close()
