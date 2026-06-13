import logging

from app.workers.celery_app import celery_app
from app.workers.document_verification import run_document_verification

logger = logging.getLogger(__name__)


@celery_app.task(name="verify_document")
def verify_document_task(document_id: int) -> dict:
    return run_document_verification(document_id)


@celery_app.task(name="send_notification_async")
def send_notification_async(notification_id: int) -> None:
    logger.info("send_notification_async %s", notification_id)
