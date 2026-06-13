"""Encolado liviano de verificación — no importa Celery ni LangChain en la petición HTTP."""

import logging
import threading
from concurrent import futures

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CELERY_ENQUEUE_TIMEOUT_SECONDS = 1.5


def _run_in_background(document_id: int) -> None:
    from app.workers.document_verification import run_document_verification

    try:
        run_document_verification(document_id)
    except Exception:
        logger.exception("Error en verificación en background del documento %s", document_id)


def enqueue_document_verification(document_id: int) -> None:
    """Encola verificación IA sin bloquear upload/login ni cargar dependencias pesadas."""
    settings = get_settings()

    if settings.is_development:
        threading.Thread(
            target=_run_in_background,
            args=(document_id,),
            daemon=True,
            name=f"verify-doc-{document_id}",
        ).start()
        return

    def dispatch_celery() -> None:
        from app.workers.tasks import verify_document_task

        verify_document_task.delay(document_id)

    try:
        with futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(dispatch_celery).result(timeout=CELERY_ENQUEUE_TIMEOUT_SECONDS)
        logger.info("Verificación encolada en Celery para documento %s", document_id)
    except Exception as exc:
        logger.warning(
            "Celery no disponible (%s); verificación del documento %s en background thread",
            exc,
            document_id,
        )
        threading.Thread(
            target=_run_in_background,
            args=(document_id,),
            daemon=True,
            name=f"verify-doc-{document_id}",
        ).start()
