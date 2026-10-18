from celery import Celery  # type: ignore[reportMissingTypeStubs]

from src.core.config import settings

celery_app = Celery(
    "mailroom",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.features.health.health_tasks"],
)
celery_app.conf.update(  # type: ignore[reportUnknownMemberType]
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
