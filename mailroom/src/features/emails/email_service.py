from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from src.core.dto import PageDto
from src.core.enums import EmailStatus
from src.core.errors import (
    BadRequestError,
    DuplicateKeyError,
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
    DEFAULT_MAX_SEND_AHEAD_DAYS = 7
    _MAX_PAGE_SIZE = 100

    def __init__(
        self,
        query: EmailServiceQueryPort,
        send_task: EmailTaskPublisher,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_send_ahead_days: int = DEFAULT_MAX_SEND_AHEAD_DAYS,
    ) -> None:
        self._query = query
        self._send_task = send_task
        self._max_attempts = self.DEFAULT_MAX_ATTEMPTS
        self.max_attempts = max_attempts
        self._max_send_ahead = timedelta(days=self.DEFAULT_MAX_SEND_AHEAD_DAYS)
        self.max_send_ahead_days = max_send_ahead_days

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @max_attempts.setter
    def max_attempts(self, value: int) -> None:
        if not 1 <= value <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        self._max_attempts = value

    @property
    def max_send_ahead_days(self) -> int:
        return self._max_send_ahead.days

    @max_send_ahead_days.setter
    def max_send_ahead_days(self, value: int) -> None:
        if not 1 <= value <= 30:
            raise ValueError("max_send_ahead_days must be between 1 and 30")
        self._max_send_ahead = timedelta(days=value)

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
        self._ensure_schedulable(send_at)

        try:
            job = self._query.add(
                self._build_job(dto, send_at, idempotency_key)
            )
        except DuplicateKeyError:
            winner = self._query.get_by_idempotency_key(idempotency_key or "")
            if winner is None:
                raise
            return EmailJobResponseDto.model_validate(winner)
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

    def _ensure_schedulable(self, send_at: datetime | None) -> None:
        if send_at is None:
            return
        now = datetime.now(timezone.utc)
        if send_at <= now:
            raise BadRequestError(
                ErrorCode.INVALID_SEND_AT,
                "sendAt must be a future date and time",
            )
        if send_at > now + self._max_send_ahead:
            raise BadRequestError(
                ErrorCode.SEND_AT_TOO_FAR,
                f"sendAt can be at most {self.max_send_ahead_days} days ahead",
            )

    def __repr__(self) -> str:
        return f"EmailService(max_attempts={self._max_attempts})"
