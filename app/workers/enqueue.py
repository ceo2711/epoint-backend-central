"""Encolado liviano en hilos — sin Celery ni Redis."""

import logging
import threading

logger = logging.getLogger(__name__)


def _spawn(name: str, target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True, name=name).start()


def _run_document_verification(document_id: int) -> None:
    from app.workers.document_verification import run_document_verification

    try:
        run_document_verification(document_id)
    except Exception:
        logger.exception("Error en verificación en background del documento %s", document_id)


def _run_attachment_verification(attachment_id: int) -> None:
    from app.workers.card_attachment_verification import run_card_attachment_verification

    try:
        run_card_attachment_verification(attachment_id)
    except Exception:
        logger.exception("Error en verificación en background del adjunto %s", attachment_id)


def enqueue_document_verification(document_id: int) -> None:
    """Lanza verificación IA en un hilo daemon sin bloquear la petición HTTP."""
    _spawn(f"verify-doc-{document_id}", _run_document_verification, document_id)


def enqueue_card_attachment_verification(attachment_id: int) -> None:
    """Lanza verificación IA de adjunto en un hilo daemon."""
    _spawn(f"verify-attachment-{attachment_id}", _run_attachment_verification, attachment_id)
