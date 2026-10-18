from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from src.core.database import db
from src.core.enums import EmailStatus
from src.domain.email_job import EmailJob
from src.features.emails.email_query import EmailQuery
from src.infrastructure.celery_app import celery_app
from src.infrastructure.mailer import MailerError, mailer


class EmailWorkerQueryPort(Protocol):
    def get_by_id(self, job_id: UUID) -> EmailJob | None: ...

    def save(self, job: EmailJob) -> EmailJob: ...


class EmailMailer(Protocol):
    def send(self, to_email: str, subject: str, body: str) -> None: ...


class EmailSendHandler:
    def __init__(self, query: EmailWorkerQueryPort, mailer: EmailMailer) -> None:
        self._query = query
        self._mailer = mailer

    def handle(self, job_id: str) -> str:
        job = self._query.get_by_id(UUID(job_id))
        if job is None:
            return "missing"
        if job.status == EmailStatus.SENT:
            return "already-sent"

        job.status = EmailStatus.SENDING
        job.attempts += 1
        self._query.save(job)
        try:
            self._mailer.send(job.to_email, job.subject, job.body)
        except MailerError as error:
            job.status = EmailStatus.RETRYING
            job.last_error = str(error)
            self._query.save(job)
            raise

        job.status = EmailStatus.SENT
        job.last_error = None
        job.sent_at = datetime.now(timezone.utc)
        self._query.save(job)
        return "sent"


@celery_app.task(  # type: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    name="emails.send"
)
def send_email_task(job_id: str) -> str:
    with db.session_scope() as session:
        return EmailSendHandler(EmailQuery(session), mailer).handle(job_id)
