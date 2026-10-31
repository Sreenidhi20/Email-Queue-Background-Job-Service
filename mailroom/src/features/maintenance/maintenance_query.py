from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus
from src.domain.dead_letter import DeadLetter
from src.domain.email_job import EmailJob


class MaintenanceQuery:
    """Bulk reads and deletes used by the scheduled jobs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def delete_sent_before(self, cutoff: datetime) -> int:
        """Delete SENT jobs whose sent_at is older than `cutoff`. Never touches other statuses."""
        statement = delete(EmailJob).where(
            EmailJob.status == EmailStatus.SENT,
            EmailJob.sent_at.is_not(None),
            EmailJob.sent_at < cutoff,
        )
        try:
            deleted = self._session.execute(statement).rowcount
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return int(deleted)

    def count_sent_since(self, since: datetime) -> int:
        return self._count(
            select(func.count()).select_from(EmailJob).where(
                EmailJob.status == EmailStatus.SENT, EmailJob.sent_at >= since
            )
        )

    def count_dead_since(self, since: datetime) -> int:
        return self._count(
            select(func.count()).select_from(DeadLetter).where(
                DeadLetter.failed_at >= since
            )
        )

    def count_with_status(self, status: EmailStatus) -> int:
        return self._count(
            select(func.count()).select_from(EmailJob).where(EmailJob.status == status)
        )

    def count_unreplayed_dead_letters(self) -> int:
        return self._count(
            select(func.count()).select_from(DeadLetter).where(
                DeadLetter.replayed.is_(False)
            )
        )

    def _count(self, statement: "select[tuple[int]]") -> int:  # type: ignore[type-arg]
        return int(self._session.scalar(statement) or 0)
