from celery import Celery  # type: ignore[reportMissingTypeStubs]
from celery.schedules import crontab  # type: ignore[reportMissingTypeStubs]

from src.core.config import settings

celery_app = Celery(
    "mailroom",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "src.features.health.health_tasks",
        "src.features.emails.email_tasks",
        "src.features.maintenance.maintenance_tasks",
    ],
)
celery_app.conf.update(  # type: ignore[reportUnknownMemberType]
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    broker_transport_options={
        "visibility_timeout": settings.redis_visibility_timeout_seconds
    },
    task_ignore_result=True,  # job state lives in the database, not the result backend
    worker_prefetch_multiplier=1,
    worker_send_task_events=True,  # Flower sees task start/finish without the -E flag
    task_send_sent_event=True,  # Flower sees tasks that are queued but not yet picked up
    beat_schedule={
        "cleanup-sent-jobs": {
            "task": "maintenance.cleanup_sent_jobs",
            "schedule": crontab(
                hour=settings.CLEANUP_HOUR_UTC, minute=settings.CLEANUP_MINUTE_UTC
            ),
        },
        "daily-digest": {
            "task": "maintenance.daily_digest",
            "schedule": crontab(
                hour=settings.DIGEST_HOUR_UTC, minute=settings.DIGEST_MINUTE_UTC
            ),
        },
    },
)
