from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging("worker")
settings = get_settings()

celery_app = Celery(
    "sin_linea",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

app = celery_app

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
