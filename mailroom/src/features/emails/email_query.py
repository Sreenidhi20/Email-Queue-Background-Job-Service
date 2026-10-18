from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus
from src.domain.email_job import EmailJob


class EmailQuery:
    """Database reads and writes for the emails feature."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: EmailJob) -> EmailJob:
        self._session.add(job)
        return self._commit(job)

    def save(self, job: EmailJob) -> EmailJob:
        return self._commit(job)

    def set_celery_task_id(self, job_id: UUID, task_id: str) -> None:
        statement = (
            update(EmailJob)
            .where(EmailJob.id == job_id)
            .values(celery_task_id=task_id)
        )
        try:
            self._session.execute(statement)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def get_by_id(self, job_id: UUID) -> EmailJob | None:
        return self._session.get(EmailJob, job_id)

    def get_by_idempotency_key(self, key: str) -> EmailJob | None:
        statement = select(EmailJob).where(EmailJob.idempotency_key == key)
        return self._session.scalars(statement).first()

    def list_paginated(
        self, status: EmailStatus | None, page: int, page_size: int
    ) -> tuple[list[EmailJob], int]:
        statement = select(EmailJob)
        count_statement = select(func.count()).select_from(EmailJob)
        if status is not None:
            statement = statement.where(EmailJob.status == status)
            count_statement = count_statement.where(EmailJob.status == status)

        total = self._session.scalar(count_statement) or 0
        rows = self._session.scalars(
            statement.order_by(EmailJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), total

    def _commit(self, job: EmailJob) -> EmailJob:
        try:
            self._session.commit()
            self._session.refresh(job)
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return job
