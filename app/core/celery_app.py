"""Celery application configuration for background worker processes."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "equipment_event_monitoring",
    broker=settings.redis_url,
    backend=settings.celery_result_backend_url,
)
celery_app.conf.update(
    imports=("app.workers.tasks",),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
