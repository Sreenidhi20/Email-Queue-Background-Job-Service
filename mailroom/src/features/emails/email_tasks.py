from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from celery import Task  # type: ignore[reportMissingTypeStubs]

from src.core.database import db
from src.core.enums import EmailStatus
from src.domain.email_job import EmailJob
from src.features.emails.email_query import EmailQuery
from src.infrastructure.celery_app import celery_app
from src.infrastructure.mailer import MailerError, mailer
from src.infrastructure.retry_policy import retry_policy


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
            job.last_error = str(error)
            if job.attempts >= job.max_attempts:
                job.status = EmailStatus.DEAD    # out of attempts: stop retrying
                self._query.save(job)
                return "dead"
            job.status = EmailStatus.RETRYING
            self._query.save(job)
            raise

        job.status = EmailStatus.SENT
        job.last_error = None
        job.sent_at = datetime.now(timezone.utc)
        self._query.save(job)
        return "sent"


@celery_app.task(  # type: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    bind=True,
    name="emails.send",
    max_retries=None,  # our handler decides when to stop (job.max_attempts)
)
def send_email_task(self: Task, job_id: str) -> str:  # type: ignore[reportMissingTypeArgument]
    with db.session_scope() as session:
        handler = EmailSendHandler(EmailQuery(session), mailer)
        try:
            return handler.handle(job_id)
        except MailerError as error:
            delay = retry_policy.delay_for(self.request.retries)
            raise self.retry(exc=error, countdown=delay) from error
