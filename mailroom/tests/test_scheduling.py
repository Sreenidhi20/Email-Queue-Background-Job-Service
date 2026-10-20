import unittest
from datetime import datetime, timedelta, timezone

from src.core.config import Settings
from src.core.errors import BadRequestError, ErrorCode
from src.features.emails.dto.email_dto import CreateEmailRequestDto
from src.features.emails.email_service import EmailService
from tests.test_emails import FakeEmailQuery, FakeTask


def make_dto(send_at: datetime | None) -> CreateEmailRequestDto:
    return CreateEmailRequestDto(
        to_email="test@example.com", subject="Hi", body="Body", send_at=send_at
    )


class SchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query = FakeEmailQuery()
        self.task = FakeTask()
        self.service = EmailService(self.query, self.task, max_send_ahead_days=7)

    def test_job_within_horizon_is_published_with_eta(self) -> None:
        send_at = datetime.now(timezone.utc) + timedelta(days=3)

        result = self.service.create(make_dto(send_at))

        self.assertEqual(self.task.calls[0][1], send_at)
        self.assertEqual(result.scheduled_for, send_at)
        self.assertEqual(result.status.value, "queued")

    def test_job_beyond_horizon_is_rejected_and_not_persisted(self) -> None:
        send_at = datetime.now(timezone.utc) + timedelta(days=8)

        with self.assertRaises(BadRequestError) as raised:
            self.service.create(make_dto(send_at))

        self.assertEqual(raised.exception.code, ErrorCode.SEND_AT_TOO_FAR)
        self.assertEqual(self.query.jobs, {})
        self.assertEqual(self.task.calls, [])

    def test_job_just_inside_horizon_is_accepted(self) -> None:
        send_at = datetime.now(timezone.utc) + timedelta(days=7) - timedelta(minutes=1)
        self.service.create(make_dto(send_at))
        self.assertEqual(len(self.task.calls), 1)

    def test_no_send_at_means_immediate_publish_without_eta(self) -> None:
        self.service.create(make_dto(None))
        self.assertIsNone(self.task.calls[0][1])

    def test_horizon_setter_rejects_out_of_range_values(self) -> None:
        with self.assertRaises(ValueError):
            self.service.max_send_ahead_days = 0
        with self.assertRaises(ValueError):
            self.service.max_send_ahead_days = 31


class VisibilityTimeoutTests(unittest.TestCase):
    def test_timeout_always_exceeds_longest_accepted_delay(self) -> None:
        for days in (1, 7, 30):
            settings = Settings(DATABASE_URL="sqlite://", MAX_SEND_AHEAD_DAYS=days)
            self.assertGreater(
                settings.redis_visibility_timeout_seconds, days * 24 * 60 * 60
            )


if __name__ == "__main__":
    unittest.main()
