"""Tareas periódicas dentro del proceso de la API (sin Celery Beat)."""

from __future__ import annotations

import logging
import threading

from app.core.config import Settings

logger = logging.getLogger(__name__)

_start_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_scheduler_stop: threading.Event | None = None
STARTUP_DELAY_SECONDS = 90


def _reminder_loop(interval_minutes: int, stop_event: threading.Event) -> None:
    from app.workers.onboarding_reminders import run_onboarding_reminders_job
    from app.workers.sub_seller_eligibility import run_sub_seller_eligibility_enforcement_job

    logger.info(
        "Recordatorios de onboarding activos — primer ciclo en %s s, luego cada %s min",
        STARTUP_DELAY_SECONDS,
        interval_minutes,
    )
    if stop_event.wait(STARTUP_DELAY_SECONDS):
        return
    while not stop_event.is_set():
        if stop_event.is_set():
            break
        try:
            run_onboarding_reminders_job(stop_event=stop_event)
        except Exception:
            if stop_event.is_set():
                break
            logger.exception("Error en ciclo de recordatorios onboarding")

        if stop_event.is_set():
            break
        try:
            run_sub_seller_eligibility_enforcement_job(stop_event=stop_event)
        except Exception:
            if stop_event.is_set():
                break
            logger.exception("Error en ciclo de elegibilidad subvendedores")

        if stop_event.wait(interval_minutes * 60):
            break


def start_onboarding_reminder_scheduler(settings: Settings) -> threading.Event | None:
    global _scheduler_thread, _scheduler_stop

    if settings.onboarding_reminder_interval_minutes <= 0:
        return None

    with _start_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            logger.warning(
                "Scheduler de recordatorios ya estaba activo — se omitió un segundo arranque"
            )
            return _scheduler_stop

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_reminder_loop,
            args=(settings.onboarding_reminder_interval_minutes, stop_event),
            daemon=True,
            name="onboarding-reminders",
        )
        thread.start()
        _scheduler_thread = thread
        _scheduler_stop = stop_event
        return stop_event


def stop_onboarding_reminder_scheduler() -> None:
    """Detiene el hilo del scheduler (p. ej. al apagar la API)."""
    global _scheduler_thread, _scheduler_stop

    with _start_lock:
        thread = _scheduler_thread
        if _scheduler_stop is not None:
            _scheduler_stop.set()
        _scheduler_thread = None
        _scheduler_stop = None

    if thread is not None and thread.is_alive():
        thread.join(timeout=2)
        if thread.is_alive():
            logger.warning(
                "El scheduler de recordatorios sigue activo (p. ej. esperando la BD); "
                "se abortará al cerrar el proceso."
            )
