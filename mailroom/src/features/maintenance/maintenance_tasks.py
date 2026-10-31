from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import db
from src.features.emails.email_query import EmailQuery
from src.features.emails.email_service import EmailService
from src.features.maintenance.maintenance_query import MaintenanceQuery
from src.features.maintenance.maintenance_service import MaintenanceService
from src.infrastructure.celery_app import celery_app
from src.infrastructure.celery_task_publisher import CeleryTaskPublisher


def build_maintenance_service(session: Session) -> MaintenanceService:
    return MaintenanceService(
        MaintenanceQuery(session),
        EmailService(EmailQuery(session), CeleryTaskPublisher("emails.send")),
        digest_to=settings.DIGEST_TO_EMAIL,
        retention_days=settings.SENT_RETENTION_DAYS,
    )


@celery_app.task(  # type: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    name="maintenance.cleanup_sent_jobs"
)
def cleanup_sent_jobs_task() -> int:
    with db.session_scope() as session:
        return build_maintenance_service(session).cleanup_sent_jobs()


@celery_app.task(  # type: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    name="maintenance.daily_digest"
)
def daily_digest_task() -> str:
    with db.session_scope() as session:
        return build_maintenance_service(session).send_daily_digest()
