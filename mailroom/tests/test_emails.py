import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus
from src.core.errors import BadRequestError
from src.domain.base import Base
from src.domain.email_job import EmailJob
from src.features.emails.dto.email_dto import CreateEmailRequestDto
from src.features.emails.email_query import EmailQuery
from src.features.emails.email_service import EmailService
from src.features.emails.email_tasks import EmailSendHandler
from src.infrastructure.mailer import MailerError


def make_job(
    *,
    status: EmailStatus = EmailStatus.QUEUED,
    idempotency_key: str | None = None,
) -> EmailJob:
    return EmailJob(
        id=uuid4(),
        to_email="test@example.com",
        subject="Hello",
        body="Test email body",
        status=status,
        attempts=0,
        max_attempts=5,
        last_error=None,
        scheduled_for=None,
        idempotency_key=idempotency_key,
        celery_task_id=None,
        created_at=datetime.now(timezone.utc),
        sent_at=None,
    )


class FakeEmailQuery:
    def __init__(self) -> None:
        self.jobs: dict[UUID, EmailJob] = {}

    def add(self, job: EmailJob) -> EmailJob:
        job.id = uuid4()
        job.created_at = datetime.now(timezone.utc)
        self.jobs[job.id] = job
        return job

    def save(self, job: EmailJob) -> EmailJob:
        self.jobs[job.id] = job
        return job

    def set_celery_task_id(self, job_id: UUID, task_id: str) -> None:
        self.jobs[job_id].celery_task_id = task_id

    def get_by_id(self, job_id: UUID) -> EmailJob | None:
        return self.jobs.get(job_id)

    def get_by_idempotency_key(self, key: str) -> EmailJob | None:
        return next(
            (job for job in self.jobs.values() if job.idempotency_key == key),
            None,
        )

    def list_paginated(
        self, status: EmailStatus | None, page: int, page_size: int
    ) -> tuple[list[EmailJob], int]:
        jobs = [
            job
            for job in self.jobs.values()
            if status is None or job.status == status
        ]
        return jobs[(page - 1) * page_size : page * page_size], len(jobs)


class FakeTask:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], datetime | None]] = []

    def apply_async(self, *, args: list[str], eta: datetime | None) -> str:
        self.calls.append((args, eta))
        return f"task-{len(self.calls)}"


class FakeMailer:
    def __init__(self, error: MailerError | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to_email: str, subject: str, body: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((to_email, subject, body))


class EmailServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query = FakeEmailQuery()
        self.task = FakeTask()
        self.service = EmailService(self.query, self.task)
        self.dto = CreateEmailRequestDto(
            to_email="test@example.com",
            subject="Hello",
            body="Test email body",
        )

    def test_create_persists_job_and_enqueues_once(self) -> None:
        response = self.service.create(self.dto)

        self.assertEqual(response.status, EmailStatus.QUEUED)
        self.assertEqual(response.attempts, 0)
        self.assertEqual(self.task.calls, [([str(response.id)], None)])
        self.assertEqual(
            self.query.jobs[response.id].celery_task_id,
            "task-1",
        )

    def test_create_returns_same_job_for_repeated_idempotency_key(self) -> None:
        first = self.service.create(self.dto, "request-1")
        second = self.service.create(self.dto, "request-1")

        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.query.jobs), 1)
        self.assertEqual(len(self.task.calls), 1)

    def test_create_rejects_past_send_at_without_persisting_or_enqueuing(self) -> None:
        past_dto = CreateEmailRequestDto(
            to_email="test@example.com",
            subject="Hello",
            body="Test email body",
            send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        with self.assertRaises(BadRequestError):
            self.service.create(past_dto)

        self.assertEqual(self.query.jobs, {})
        self.assertEqual(self.task.calls, [])

    def test_create_normalizes_naive_future_send_at_to_utc(self) -> None:
        send_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        dto = CreateEmailRequestDto(
            to_email="test@example.com",
            subject="Hello",
            body="Test email body",
            send_at=send_at,
        )

        response = self.service.create(dto)

        if response.scheduled_for is None:
            self.fail("Expected scheduled time in the response")
        self.assertEqual(response.scheduled_for.tzinfo, timezone.utc)
        self.assertEqual(self.task.calls[0][1], response.scheduled_for)

    def test_max_attempts_rejects_values_outside_supported_range(self) -> None:
        with self.assertRaises(ValueError):
            self.service.max_attempts = 0
        with self.assertRaises(ValueError):
            self.service.max_attempts = 11

    def test_request_rejects_malformed_email_address(self) -> None:
        with self.assertRaises(ValidationError):
            CreateEmailRequestDto(
                to_email="not-an-email",
                subject="Hello",
                body="Test email body",
            )


class EmailQueryTests(unittest.TestCase):
    def test_setting_task_id_does_not_overwrite_worker_status(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as api_session:
                job = EmailQuery(api_session).add(make_job())
                job_id = job.id

                with Session(engine) as worker_session:
                    worker_query = EmailQuery(worker_session)
                    worker_job = worker_query.get_by_id(job_id)
                    if worker_job is None:
                        self.fail("Worker could not load the queued job")
                    worker_job.status = EmailStatus.SENT
                    worker_job.attempts = 1
                    worker_job.sent_at = datetime.now(timezone.utc)
                    worker_query.save(worker_job)

                EmailQuery(api_session).set_celery_task_id(job_id, "celery-task-1")

            with Session(engine) as verify_session:
                saved_job = EmailQuery(verify_session).get_by_id(job_id)
                if saved_job is None:
                    self.fail("Email job was not persisted")
                self.assertEqual(saved_job.status, EmailStatus.SENT)
                self.assertEqual(saved_job.attempts, 1)
                self.assertEqual(saved_job.celery_task_id, "celery-task-1")
        finally:
            engine.dispose()


class EmailSendHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = make_job()
        self.query = FakeEmailQuery()
        self.query.add(self.job)
        self.mailer = FakeMailer()
        self.handler = EmailSendHandler(self.query, self.mailer)

    def test_handle_sends_and_marks_job_sent(self) -> None:
        result = self.handler.handle(str(self.job.id))

        self.assertEqual(result, "sent")
        self.assertEqual(self.job.status, EmailStatus.SENT)
        self.assertEqual(self.job.attempts, 1)
        self.assertIsNone(self.job.last_error)
        self.assertIsNotNone(self.job.sent_at)
        self.assertEqual(
            self.mailer.sent,
            [("test@example.com", "Hello", "Test email body")],
        )

    def test_handle_does_not_resend_already_sent_job(self) -> None:
        self.job.status = EmailStatus.SENT

        result = self.handler.handle(str(self.job.id))

        self.assertEqual(result, "already-sent")
        self.assertEqual(self.mailer.sent, [])

    def test_handle_records_mailer_failure_and_reraises(self) -> None:
        self.mailer.error = MailerError("SMTP unavailable")

        with self.assertRaisesRegex(MailerError, "SMTP unavailable"):
            self.handler.handle(str(self.job.id))

        self.assertEqual(self.job.status, EmailStatus.RETRYING)
        self.assertEqual(self.job.attempts, 1)
        self.assertEqual(self.job.last_error, "SMTP unavailable")

    def test_handle_returns_missing_for_unknown_job(self) -> None:
        self.assertEqual(self.handler.handle(str(uuid4())), "missing")
        self.assertEqual(self.mailer.sent, [])


if __name__ == "__main__":
    unittest.main()
