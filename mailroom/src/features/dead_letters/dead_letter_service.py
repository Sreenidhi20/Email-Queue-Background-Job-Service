from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.dto import PageDto
from src.core.enums import EmailStatus, ReplayOutcome
from src.core.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    ServiceUnavailableError,
)
from src.domain.dead_letter import DeadLetter
from src.features.dead_letters.dto.dead_letter_dto import (
    DeadLetterResponseDto,
    ReplayResponseDto,
)


class DeadLetterQueryPort(Protocol):
    def get_by_id(self, letter_id: UUID) -> DeadLetter | None: ...

    def list_paginated(
        self, replayed: bool | None, page: int, page_size: int
    ) -> tuple[list[DeadLetter], int]: ...

    def replay(self, letter_id: UUID) -> ReplayOutcome: ...

    def undo_replay(self, letter: DeadLetter) -> None: ...


class ReplayTaskPublisher(Protocol):
    def apply_async(self, *, args: list[str], eta: datetime | None) -> str: ...


class DeadLetterService:
    _MAX_PAGE_SIZE = 100

    def __init__(
        self, query: DeadLetterQueryPort, send_task: ReplayTaskPublisher
    ) -> None:
        self._query = query
        self._send_task = send_task

    def list(
        self, replayed: bool | None, page: int, page_size: int
    ) -> PageDto[DeadLetterResponseDto]:
        size = min(page_size, self._MAX_PAGE_SIZE)
        rows, total = self._query.list_paginated(replayed, page, size)
        items = [DeadLetterResponseDto.model_validate(row) for row in rows]
        return PageDto[DeadLetterResponseDto](
            items=items, total=total, page=page, page_size=size
        )

    def get(self, letter_id: UUID) -> DeadLetterResponseDto:
        return DeadLetterResponseDto.model_validate(self._get_or_raise(letter_id))

    def replay(self, letter_id: UUID) -> ReplayResponseDto:
        letter = self._get_or_raise(letter_id)
        self._raise_if_not_replayable(self._query.replay(letter_id), letter_id)
        try:
            self._send_task.apply_async(args=[str(letter.email_job_id)], eta=None)
        except ServiceUnavailableError:
            self._query.undo_replay(letter)      # nothing was queued: restore state
            raise
        return ReplayResponseDto(
            dead_letter_id=letter.id,
            email_job_id=letter.email_job_id,
            status=EmailStatus.QUEUED,
        )

    def _get_or_raise(self, letter_id: UUID) -> DeadLetter:
        letter = self._query.get_by_id(letter_id)
        if letter is None:
            raise NotFoundError(
                ErrorCode.DEAD_LETTER_NOT_FOUND,
                f"Dead letter {letter_id} does not exist",
            )
        return letter

    @staticmethod
    def _raise_if_not_replayable(outcome: ReplayOutcome, letter_id: UUID) -> None:
        if outcome == ReplayOutcome.ALREADY_REPLAYED:
            raise ConflictError(
                ErrorCode.DEAD_LETTER_ALREADY_REPLAYED,
                f"Dead letter {letter_id} was already replayed",
            )
        if outcome == ReplayOutcome.JOB_NOT_DEAD:
            raise ConflictError(
                ErrorCode.EMAIL_JOB_NOT_DEAD,
                "The email job is no longer in the dead state",
            )
