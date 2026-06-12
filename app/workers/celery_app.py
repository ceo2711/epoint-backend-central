from celery import Celery

from app.core.config import get_settings

settings = get_settings()

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
)

# Importar tareas para registro
import app.workers.tasks  # noqa: E402, F401
