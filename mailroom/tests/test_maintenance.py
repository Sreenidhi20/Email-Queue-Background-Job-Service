import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus
from src.domain.base import Base
from src.domain.dead_letter import DeadLetter
from src.domain.email_job import EmailJob
from src.features.emails.dto.email_dto import (
    CreateEmailRequestDto,
    EmailJobResponseDto,
)
from src.features.emails.email_query import EmailQuery
from src.features.maintenance.maintenance_query import MaintenanceQuery
from src.features.maintenance.maintenance_service import MaintenanceService
from src.infrastructure.celery_app import celery_app
from tests.test_emails import make_job

NOW = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)


def job_with(status: EmailStatus, sent_days_ago: float | None = None) -> EmailJob:
    job = make_job(status=status)
    if sent_days_ago is not None:
        job.sent_at = NOW - timedelta(days=sent_days_ago)
    return job


class MaintenanceQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.emails = EmailQuery(self.session)
        self.query = MaintenanceQuery(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_delete_removes_only_old_sent_jobs(self) -> None:
        old_sent_id = self.emails.add(job_with(EmailStatus.SENT, 40)).id
        self.emails.add(job_with(EmailStatus.SENT, 5))
        self.emails.add(job_with(EmailStatus.DEAD, None))
        self.emails.add(job_with(EmailStatus.QUEUED, None))

        deleted = self.query.delete_sent_before(NOW - timedelta(days=30))

        self.assertEqual(deleted, 1)
        self.assertIsNone(self.session.get(EmailJob, old_sent_id))
        remaining = self.session.scalars(select(EmailJob)).all()
        self.assertEqual(len(remaining), 3)
        self.assertEqual(
            sorted(j.status.value for j in remaining), ["dead", "queued", "sent"]
        )

    def test_old_dead_job_is_never_deleted_even_if_it_has_sent_at(self) -> None:
        dead_id = self.emails.add(job_with(EmailStatus.DEAD, 90)).id   # odd data: dead but old sent_at

        self.assertEqual(self.query.delete_sent_before(NOW), 0)
        self.assertIsNotNone(self.session.get(EmailJob, dead_id))

    def test_counts_for_digest(self) -> None:
        self.emails.add(job_with(EmailStatus.SENT, 0.5))
        self.emails.add(job_with(EmailStatus.SENT, 3))
        self.emails.add(job_with(EmailStatus.QUEUED))
        self.emails.add(job_with(EmailStatus.QUEUED))
        self.emails.add(job_with(EmailStatus.RETRYING))
        dead = self.emails.add(job_with(EmailStatus.DEAD))
        self.session.add(
            DeadLetter(
                email_job_id=dead.id, to_email="a@b.com", subject="s",
                error="boom", attempts=5, failed_at=NOW - timedelta(hours=2),
            )
        )
        self.session.commit()
        since = NOW - timedelta(hours=24)

        self.assertEqual(self.query.count_sent_since(since), 1)
        self.assertEqual(self.query.count_dead_since(since), 1)
        self.assertEqual(self.query.count_with_status(EmailStatus.QUEUED), 2)
        self.assertEqual(self.query.count_with_status(EmailStatus.RETRYING), 1)
        self.assertEqual(self.query.count_unreplayed_dead_letters(), 1)


class FakeMaintenanceQuery:
    def __init__(self) -> None:
        self.cutoffs: list[datetime] = []

    def delete_sent_before(self, cutoff: datetime) -> int:
        self.cutoffs.append(cutoff)
        return 7

    def count_sent_since(self, since: datetime) -> int:
        return 12

    def count_dead_since(self, since: datetime) -> int:
        return 2

    def count_with_status(self, status: EmailStatus) -> int:
        return {EmailStatus.QUEUED: 3, EmailStatus.RETRYING: 1}.get(status, 0)

    def count_unreplayed_dead_letters(self) -> int:
        return 4


class FakeSubmitter:
    def __init__(self) -> None:
        self.calls: list[tuple[CreateEmailRequestDto, str | None]] = []

    def create(
        self, dto: CreateEmailRequestDto, idempotency_key: str | None = None
    ) -> EmailJobResponseDto:
        self.calls.append((dto, idempotency_key))
        return EmailJobResponseDto.model_validate(
            {
                "id": "00000000-0000-0000-0000-000000000001", "toEmail": str(dto.to_email),
                "subject": dto.subject, "status": "queued", "attempts": 0,
                "createdAt": NOW.isoformat(),
            }
        )


class MaintenanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query = FakeMaintenanceQuery()
        self.submitter = FakeSubmitter()
        self.service = MaintenanceService(
            self.query, self.submitter, digest_to="me@example.com", retention_days=30
        )

    def test_cleanup_uses_retention_window(self) -> None:
        deleted = self.service.cleanup_sent_jobs(NOW)

        self.assertEqual(deleted, 7)
        self.assertEqual(self.query.cutoffs, [NOW - timedelta(days=30)])

    def test_digest_is_queued_through_email_service_with_daily_key(self) -> None:
        result = self.service.send_daily_digest(NOW)

        self.assertEqual(result, "queued")
        dto, key = self.submitter.calls[0]
        self.assertEqual(str(dto.to_email), "me@example.com")
        self.assertEqual(dto.subject, "Mailroom daily digest 2026-10-26")
        self.assertEqual(key, "daily-digest-2026-10-26")
        self.assertIn("Sent:                    12", dto.body)
        self.assertIn("Failed permanently:      2", dto.body)
        self.assertIn("Dead letters to review:  4", dto.body)

    def test_digest_is_skipped_without_recipient(self) -> None:
        service = MaintenanceService(self.query, self.submitter, digest_to=None)

        self.assertTrue(service.send_daily_digest(NOW).startswith("skipped"))
        self.assertEqual(self.submitter.calls, [])

    def test_retention_setter_rejects_out_of_range_values(self) -> None:
        with self.assertRaises(ValueError):
            self.service.retention_days = 0
        with self.assertRaises(ValueError):
            self.service.retention_days = 366


class BeatScheduleTests(unittest.TestCase):
    def test_both_jobs_are_scheduled_daily_in_utc(self) -> None:
        schedule = celery_app.conf.beat_schedule

        self.assertEqual(
            {entry["task"] for entry in schedule.values()},
            {"maintenance.cleanup_sent_jobs", "maintenance.daily_digest"},
        )
        digest = schedule["daily-digest"]["schedule"]
        self.assertEqual((digest.hour, digest.minute), ({2}, {30}))
        cleanup = schedule["cleanup-sent-jobs"]["schedule"]
        self.assertEqual((cleanup.hour, cleanup.minute), ({21}, {30}))
        self.assertEqual(celery_app.conf.timezone, "UTC")


if __name__ == "__main__":
    unittest.main()
