from celery import Celery

from app.core.config import get_settings

settings = get_settings()

# Celery opcional (legacy). La API usa hilos en background; no hace falta worker ni Redis.
celery_app = Celery(
    "epoint_crm",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
)

import app.workers.tasks  # noqa: E402, F401
