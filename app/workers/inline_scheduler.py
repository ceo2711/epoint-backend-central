"""Tareas periódicas dentro del proceso de la API (sin Celery Beat)."""

from __future__ import annotations

import logging
import threading

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _reminder_loop(interval_minutes: int, stop_event: threading.Event) -> None:
    from app.workers.onboarding_reminders import run_onboarding_reminders_job

    logger.info(
        "Recordatorios de onboarding activos — cada %s min (primer ciclo al iniciar)",
        interval_minutes,
    )
    while not stop_event.is_set():
        try:
            summary = run_onboarding_reminders_job()
            logger.info("Ciclo de recordatorios onboarding: %s", summary)
        except Exception:
            logger.exception("Error en ciclo de recordatorios onboarding")

        if stop_event.wait(interval_minutes * 60):
            break


def start_onboarding_reminder_scheduler(settings: Settings) -> threading.Event | None:
    if settings.onboarding_reminder_interval_minutes <= 0:
        return None

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_reminder_loop,
        args=(settings.onboarding_reminder_interval_minutes, stop_event),
        daemon=True,
        name="onboarding-reminders",
    )
    thread.start()
    return stop_event
