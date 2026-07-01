"""Bloqueo distribuido para el job de recordatorios (evita duplicados entre procesos uvicorn)."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Clave fija para pg_advisory_lock (un solo job global de recordatorios)
_REMINDER_JOB_LOCK_KEY = 8_392_742_1


def try_acquire_reminder_job_lock(db: Session) -> bool:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return True

    acquired = bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _REMINDER_JOB_LOCK_KEY}).scalar())
    if not acquired:
        logger.info("Ciclo de recordatorios omitido: otro proceso uvicorn ya lo está ejecutando")
    return acquired


def release_reminder_job_lock(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _REMINDER_JOB_LOCK_KEY})
