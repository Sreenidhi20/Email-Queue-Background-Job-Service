from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus, ReplayOutcome
from src.domain.dead_letter import DeadLetter
from src.domain.email_job import EmailJob


class DeadLetterQuery:
    """Database reads and writes for the dead-letters feature."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, letter_id: UUID) -> DeadLetter | None:
        return self._session.get(DeadLetter, letter_id)

    def list_paginated(
        self, replayed: bool | None, page: int, page_size: int
    ) -> tuple[list[DeadLetter], int]:
        statement = select(DeadLetter)
        count_statement = select(func.count()).select_from(DeadLetter)
        if replayed is not None:
            statement = statement.where(DeadLetter.replayed.is_(replayed))
            count_statement = count_statement.where(DeadLetter.replayed.is_(replayed))

        total = self._session.scalar(count_statement) or 0
        rows = self._session.scalars(
            statement.order_by(DeadLetter.failed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), total

    def replay(self, letter_id: UUID) -> ReplayOutcome:
        """Atomically mark the letter replayed AND reset its job to `queued`.

        Both are conditional UPDATEs in one transaction, so two simultaneous
        replay requests cannot both succeed.
        """
        try:
            claimed = self._session.execute(
                update(DeadLetter)
                .where(DeadLetter.id == letter_id, DeadLetter.replayed.is_(False))
                .values(replayed=True, replayed_at=datetime.now(timezone.utc))
            ).rowcount
            if claimed != 1:
                self._session.rollback()
                return ReplayOutcome.ALREADY_REPLAYED

            job_id = self._session.scalar(
                select(DeadLetter.email_job_id).where(DeadLetter.id == letter_id)
            )
            reset = self._session.execute(
                update(EmailJob)
                .where(EmailJob.id == job_id, EmailJob.status == EmailStatus.DEAD)
                .values(
                    status=EmailStatus.QUEUED,
                    attempts=0,
                    last_error=None,
                    sent_at=None,
                    scheduled_for=None,
                    celery_task_id=None,
                )
            ).rowcount
            if reset != 1:
                self._session.rollback()
                return ReplayOutcome.JOB_NOT_DEAD

            self._session.commit()
            return ReplayOutcome.REPLAYED
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def undo_replay(self, letter: DeadLetter) -> None:
        """Put the letter and its job back as they were (used if queueing fails)."""
        try:
            self._session.execute(
                update(DeadLetter)
                .where(DeadLetter.id == letter.id)
                .values(replayed=False, replayed_at=None)
            )
            self._session.execute(
                update(EmailJob)
                .where(EmailJob.id == letter.email_job_id)
                .values(
                    status=EmailStatus.DEAD,
                    attempts=letter.attempts,
                    last_error=letter.error,
                )
            )
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
