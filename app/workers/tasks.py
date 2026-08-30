import logging

from app.workers.celery_app import celery_app
from app.workers.document_verification import run_document_verification

logger = logging.getLogger(__name__)


@celery_app.task(name="verify_document")
def verify_document_task(document_id: int) -> dict:
    return run_document_verification(document_id)


@celery_app.task(name="verify_card_attachment")
def verify_card_attachment_task(attachment_id: int) -> dict:
    from app.workers.card_attachment_verification import run_card_attachment_verification

    return run_card_attachment_verification(attachment_id)


@celery_app.task(name="send_notification_async")
def send_notification_async(notification_id: int) -> None:
    logger.info("send_notification_async %s", notification_id)


@celery_app.task(name="send_onboarding_reminders")
def send_onboarding_reminders_task() -> dict:
    from app.workers.onboarding_reminders import run_onboarding_reminders_job

    return run_onboarding_reminders_job()


@celery_app.task(name="send_board_reminders")
def send_board_reminders_task() -> dict:
    from app.workers.board_reminders import run_board_reminders_job

    return run_board_reminders_job()


@celery_app.task(name="enforce_sub_seller_eligibility")
def enforce_sub_seller_eligibility_task() -> dict:
    from app.workers.sub_seller_eligibility import run_sub_seller_eligibility_enforcement_job

    return run_sub_seller_eligibility_enforcement_job()
