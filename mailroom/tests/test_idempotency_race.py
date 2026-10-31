import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.core.errors import DuplicateKeyError
from src.domain.base import Base
from src.domain.email_job import EmailJob
from src.features.emails.dto.email_dto import CreateEmailRequestDto
from src.features.emails.email_query import EmailQuery
from src.features.emails.email_service import EmailService
from tests.test_emails import FakeTask, make_job


class LosingRaceQuery:
    """Simulates request B: the key looked free, then another request inserted it first."""

    def __init__(self, winner: EmailJob) -> None:
        self.winner = winner
        self.lookups = 0

    def get_by_idempotency_key(self, key: str) -> EmailJob | None:
        self.lookups += 1
        return None if self.lookups == 1 else self.winner

    def add(self, job: EmailJob) -> EmailJob:
        raise DuplicateKeyError(job.idempotency_key or "")


class IdempotencyRaceTests(unittest.TestCase):
    def test_query_raises_duplicate_key_error_when_the_key_already_exists(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                query = EmailQuery(session)
                query.add(make_job(idempotency_key="same-key"))

                with self.assertRaises(DuplicateKeyError):
                    query.add(make_job(idempotency_key="same-key"))

                self.assertEqual(
                    session.scalar(select(func.count()).select_from(EmailJob)), 1
                )
        finally:
            engine.dispose()

    def test_other_integrity_errors_are_not_mistaken_for_duplicates(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                job = make_job()
                job.to_email = None  # type: ignore[assignment]

                with self.assertRaises(Exception) as raised:
                    EmailQuery(session).add(job)

                self.assertNotIsInstance(raised.exception, DuplicateKeyError)
        finally:
            engine.dispose()

    def test_service_returns_the_winning_job_instead_of_failing(self) -> None:
        winner = make_job(idempotency_key="k")
        task = FakeTask()
        service = EmailService(LosingRaceQuery(winner), task)  # type: ignore[arg-type]
        dto = CreateEmailRequestDto(to_email="a@b.com", subject="s", body="b")

        result = service.create(dto, "k")

        self.assertEqual(result.id, winner.id)
        self.assertEqual(task.calls, [])           # the loser must not queue a second email


if __name__ == "__main__":
    unittest.main()
