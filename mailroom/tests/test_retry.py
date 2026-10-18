import random
import unittest
from datetime import datetime

from src.core.enums import EmailStatus
from src.core.errors import ErrorCode, ServiceUnavailableError
from src.features.emails.dto.email_dto import CreateEmailRequestDto
from src.features.emails.email_service import EmailService
from src.features.emails.email_tasks import EmailSendHandler
from src.infrastructure.mailer import MailerError
from src.infrastructure.retry_policy import RetryPolicy
from tests.test_emails import FakeEmailQuery, FakeMailer, make_job


class RetryPolicyTests(unittest.TestCase):
    def test_delay_doubles_and_is_capped_without_jitter(self) -> None:
        policy = RetryPolicy(base_seconds=10, max_seconds=100, jitter=False)

        delays = [policy.delay_for(n) for n in range(6)]

        self.assertEqual(delays, [10, 20, 40, 80, 100, 100])

    def test_jitter_stays_between_half_and_full_delay(self) -> None:
        policy = RetryPolicy(10, 600, jitter=True, rng=random.Random(1))

        for retry_number in range(8):
            ceiling = min(600, 10 * 2**retry_number)
            delay = policy.delay_for(retry_number)
            self.assertGreaterEqual(delay, ceiling // 2)
            self.assertLessEqual(delay, ceiling)

    def test_huge_retry_number_does_not_overflow(self) -> None:
        policy = RetryPolicy(10, 600, jitter=False)
        self.assertEqual(policy.delay_for(10_000), 600)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(0, 10)
        with self.assertRaises(ValueError):
            RetryPolicy(20, 10)


class DeadAfterMaxAttemptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = make_job()
        self.job.max_attempts = 3
        self.query = FakeEmailQuery()
        self.query.add(self.job)
        self.handler = EmailSendHandler(
            self.query, FakeMailer(MailerError("SMTP unavailable"))
        )

    def test_retries_until_last_attempt_then_marks_dead(self) -> None:
        for expected_attempt in (1, 2):
            with self.assertRaises(MailerError):
                self.handler.handle(str(self.job.id))
            self.assertEqual(self.job.status, EmailStatus.RETRYING)
            self.assertEqual(self.job.attempts, expected_attempt)

        result = self.handler.handle(str(self.job.id))

        self.assertEqual(result, "dead")
        self.assertEqual(self.job.status, EmailStatus.DEAD)
        self.assertEqual(self.job.attempts, 3)
        self.assertEqual(self.job.last_error, "SMTP unavailable")


class FailingPublisher:
    def apply_async(self, *, args: list[str], eta: datetime | None) -> str:
        raise ServiceUnavailableError(ErrorCode.QUEUE_UNAVAILABLE, "redis down")


class PublishFailureTests(unittest.TestCase):
    def test_failed_publish_removes_row_and_raises(self) -> None:
        query = FakeEmailQuery()
        service = EmailService(query, FailingPublisher())
        dto = CreateEmailRequestDto(
            to_email="test@example.com", subject="Hi", body="Body"
        )

        with self.assertRaises(ServiceUnavailableError):
            service.create(dto, "key-1")

        self.assertEqual(query.jobs, {})
        self.assertIsNone(query.get_by_idempotency_key("key-1"))


if __name__ == "__main__":
    unittest.main()
