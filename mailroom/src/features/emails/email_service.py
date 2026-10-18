from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from src.core.dto import PageDto
from src.core.enums import EmailStatus
from src.core.errors import (
    BadRequestError,
    ErrorCode,
    NotFoundError,
    ServiceUnavailableError,
)
from src.domain.email_job import EmailJob
from src.features.emails.dto.email_dto import (
    CreateEmailRequestDto,
    EmailJobResponseDto,
)


class EmailServiceQueryPort(Protocol):
    def add(self, job: EmailJob) -> EmailJob: ...

    def save(self, job: EmailJob) -> EmailJob: ...

    def set_celery_task_id(self, job_id: UUID, task_id: str) -> None: ...

    def delete(self, job: EmailJob) -> None: ...

    def get_by_id(self, job_id: UUID) -> EmailJob | None: ...

    def get_by_idempotency_key(self, key: str) -> EmailJob | None: ...

    def list_paginated(
        self, status: EmailStatus | None, page: int, page_size: int
    ) -> tuple[list[EmailJob], int]: ...


class EmailTaskPublisher(Protocol):
    def apply_async(self, *, args: list[str], eta: datetime | None) -> str: ...


class EmailService:
    DEFAULT_MAX_ATTEMPTS = 5
    _MAX_PAGE_SIZE = 100

    def __init__(
        self,
        query: EmailServiceQueryPort,
        send_task: EmailTaskPublisher,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._query = query
        self._send_task = send_task
        self._max_attempts = self.DEFAULT_MAX_ATTEMPTS
        self.max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @max_attempts.setter
    def max_attempts(self, value: int) -> None:
        if not 1 <= value <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        self._max_attempts = value

    def create(
        self,
        dto: CreateEmailRequestDto,
        idempotency_key: str | None = None,
    ) -> EmailJobResponseDto:
        if idempotency_key is not None:
            existing = self._query.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return EmailJobResponseDto.model_validate(existing)

        send_at = self._normalize_utc(dto.send_at)
        self._ensure_in_future(send_at)

        job = self._query.add(
            self._build_job(dto, send_at, idempotency_key)
        )
        self._enqueue(job)
        return EmailJobResponseDto.model_validate(job)

    def get(self, job_id: UUID) -> EmailJobResponseDto:
        return EmailJobResponseDto.model_validate(self._get_or_raise(job_id))

    def list(
        self, status: EmailStatus | None, page: int, page_size: int
    ) -> PageDto[EmailJobResponseDto]:
        size = min(page_size, self._MAX_PAGE_SIZE)
        rows, total = self._query.list_paginated(status, page, size)
        items = [EmailJobResponseDto.model_validate(row) for row in rows]
        return PageDto[EmailJobResponseDto](
            items=items, total=total, page=page, page_size=size
        )

    def _get_or_raise(self, job_id: UUID) -> EmailJob:
        job = self._query.get_by_id(job_id)
        if job is None:
            raise NotFoundError(
                ErrorCode.EMAIL_JOB_NOT_FOUND,
                f"Email job {job_id} does not exist",
            )
        return job

    def _build_job(
        self,
        dto: CreateEmailRequestDto,
        send_at: datetime | None,
        key: str | None,
    ) -> EmailJob:
        return EmailJob(
            to_email=str(dto.to_email),
            subject=dto.subject,
            body=dto.body,
            status=EmailStatus.QUEUED,
            attempts=0,
            max_attempts=self._max_attempts,
            scheduled_for=send_at,
            idempotency_key=key,
        )

    def _enqueue(self, job: EmailJob) -> None:
        try:
            task_id = self._send_task.apply_async(
                args=[str(job.id)], eta=job.scheduled_for
            )
        except ServiceUnavailableError:
            # The row was committed before publishing. Remove it so a client
            # retry (even with the same Idempotency-Key) starts clean.
            self._query.delete(job)
            raise
        self._query.set_celery_task_id(job.id, task_id)

    @staticmethod
    def _normalize_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _ensure_in_future(send_at: datetime | None) -> None:
        if send_at is not None and send_at <= datetime.now(timezone.utc):
            raise BadRequestError(
                ErrorCode.INVALID_SEND_AT,
                "sendAt must be a future date and time",
            )

    def __repr__(self) -> str:
        return f"EmailService(max_attempts={self._max_attempts})"
