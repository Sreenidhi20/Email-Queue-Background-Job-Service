import unittest
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus, ReplayOutcome
from src.core.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    ServiceUnavailableError,
)
from src.domain.base import Base
from src.domain.dead_letter import DeadLetter
from src.domain.email_job import EmailJob
from src.features.dead_letters.dead_letter_query import DeadLetterQuery
from src.features.dead_letters.dead_letter_service import DeadLetterService
from src.features.emails.email_query import EmailQuery
from tests.test_emails import make_job


def make_dead_job() -> EmailJob:
    job = make_job(status=EmailStatus.DEAD)
    job.attempts = 5
    job.last_error = "SMTP unavailable"
    return job


def make_letter(job: EmailJob) -> DeadLetter:
    return DeadLetter(
        id=uuid4(),
        email_job_id=job.id,
        to_email=job.to_email,
        subject=job.subject,
        error="SMTP unavailable",
        attempts=5,
        failed_at=datetime.now(timezone.utc),
        replayed=False,
        replayed_at=None,
    )


class DeadLetterQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.job = EmailQuery(self.session).add(make_dead_job())
        EmailQuery(self.session).save_as_dead(self.job)
        letter = self.session.scalars(select(DeadLetter)).one()
        self.letter_id: UUID = letter.id
        self.query = DeadLetterQuery(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _job_status(self) -> EmailStatus:
        self.session.expire_all()
        job = self.session.get(EmailJob, self.job.id)
        assert job is not None
        return job.status

    def test_save_as_dead_writes_one_snapshot_row(self) -> None:
        letters = self.session.scalars(select(DeadLetter)).all()

        self.assertEqual(len(letters), 1)
        self.assertEqual(letters[0].email_job_id, self.job.id)
        self.assertEqual(letters[0].error, "SMTP unavailable")
        self.assertEqual(letters[0].attempts, 5)
        self.assertFalse(letters[0].replayed)

    def test_replay_requeues_job_and_marks_letter(self) -> None:
        outcome = self.query.replay(self.letter_id)

        self.assertEqual(outcome, ReplayOutcome.REPLAYED)
        self.session.expire_all()
        job = self.session.get(EmailJob, self.job.id)
        letter = self.session.get(DeadLetter, self.letter_id)
        assert job is not None and letter is not None
        self.assertEqual(job.status, EmailStatus.QUEUED)
        self.assertEqual(job.attempts, 0)
        self.assertIsNone(job.last_error)
        self.assertTrue(letter.replayed)
        self.assertIsNotNone(letter.replayed_at)

    def test_second_replay_is_refused(self) -> None:
        self.query.replay(self.letter_id)

        self.assertEqual(
            self.query.replay(self.letter_id), ReplayOutcome.ALREADY_REPLAYED
        )

    def test_replay_refused_and_rolled_back_when_job_not_dead(self) -> None:
        job = self.session.get(EmailJob, self.job.id)
        assert job is not None
        job.status = EmailStatus.SENT
        EmailQuery(self.session).save(job)

        outcome = self.query.replay(self.letter_id)

        self.assertEqual(outcome, ReplayOutcome.JOB_NOT_DEAD)
        self.session.expire_all()
        letter = self.session.get(DeadLetter, self.letter_id)
        assert letter is not None
        self.assertFalse(letter.replayed)      # claim was rolled back
        self.assertEqual(self._job_status(), EmailStatus.SENT)

    def test_undo_replay_restores_letter_and_job(self) -> None:
        letter = self.query.get_by_id(self.letter_id)
        assert letter is not None
        self.query.replay(self.letter_id)

        self.query.undo_replay(letter)

        self.session.expire_all()
        job = self.session.get(EmailJob, self.job.id)
        restored = self.session.get(DeadLetter, self.letter_id)
        assert job is not None and restored is not None
        self.assertEqual(job.status, EmailStatus.DEAD)
        self.assertEqual(job.attempts, 5)
        self.assertEqual(job.last_error, "SMTP unavailable")
        self.assertFalse(restored.replayed)
        self.assertIsNone(restored.replayed_at)

    def test_list_filters_by_replayed_flag(self) -> None:
        self.assertEqual(self.query.list_paginated(False, 1, 20)[1], 1)
        self.assertEqual(self.query.list_paginated(True, 1, 20)[1], 0)
        self.query.replay(self.letter_id)
        self.assertEqual(self.query.list_paginated(False, 1, 20)[1], 0)
        self.assertEqual(self.query.list_paginated(True, 1, 20)[1], 1)


class FakeLetterQuery:
    def __init__(self, outcome: ReplayOutcome = ReplayOutcome.REPLAYED) -> None:
        self.letters: dict[UUID, DeadLetter] = {}
        self.outcome = outcome
        self.undone: list[UUID] = []

    def get_by_id(self, letter_id: UUID) -> DeadLetter | None:
        return self.letters.get(letter_id)

    def list_paginated(
        self, replayed: bool | None, page: int, page_size: int
    ) -> tuple[list[DeadLetter], int]:
        rows = [r for r in self.letters.values() if replayed in (None, r.replayed)]
        return rows[(page - 1) * page_size : page * page_size], len(rows)

    def replay(self, letter_id: UUID) -> ReplayOutcome:
        return self.outcome

    def undo_replay(self, letter: DeadLetter) -> None:
        self.undone.append(letter.id)


class FakePublisher:
    def __init__(self, error: ServiceUnavailableError | None = None) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def apply_async(self, *, args: list[str], eta: datetime | None) -> str:
        if self.error is not None:
            raise self.error
        self.calls.append(args)
        return "task-1"


class DeadLetterServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = make_dead_job()
        self.letter = make_letter(self.job)
        self.query = FakeLetterQuery()
        self.query.letters[self.letter.id] = self.letter
        self.publisher = FakePublisher()
        self.service = DeadLetterService(self.query, self.publisher)

    def test_replay_publishes_job_id_and_reports_queued(self) -> None:
        result = self.service.replay(self.letter.id)

        self.assertEqual(self.publisher.calls, [[str(self.job.id)]])
        self.assertEqual(result.status, EmailStatus.QUEUED)
        self.assertEqual(result.email_job_id, self.job.id)

    def test_replay_unknown_letter_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError) as raised:
            self.service.replay(uuid4())

        self.assertEqual(raised.exception.code, ErrorCode.DEAD_LETTER_NOT_FOUND)

    def test_already_replayed_maps_to_conflict_without_publishing(self) -> None:
        self.query.outcome = ReplayOutcome.ALREADY_REPLAYED

        with self.assertRaises(ConflictError) as raised:
            self.service.replay(self.letter.id)

        self.assertEqual(raised.exception.code, ErrorCode.DEAD_LETTER_ALREADY_REPLAYED)
        self.assertEqual(self.publisher.calls, [])

    def test_job_not_dead_maps_to_conflict(self) -> None:
        self.query.outcome = ReplayOutcome.JOB_NOT_DEAD

        with self.assertRaises(ConflictError) as raised:
            self.service.replay(self.letter.id)

        self.assertEqual(raised.exception.code, ErrorCode.EMAIL_JOB_NOT_DEAD)

    def test_queue_failure_undoes_replay_and_reraises(self) -> None:
        self.publisher.error = ServiceUnavailableError(ErrorCode.QUEUE_UNAVAILABLE)

        with self.assertRaises(ServiceUnavailableError):
            self.service.replay(self.letter.id)

        self.assertEqual(self.query.undone, [self.letter.id])

    def test_list_returns_page_dto(self) -> None:
        page = self.service.list(False, 1, 500)

        self.assertEqual(page.total, 1)
        self.assertEqual(page.page_size, 100)
        self.assertEqual(page.items[0].id, self.letter.id)


if __name__ == "__main__":
    unittest.main()
