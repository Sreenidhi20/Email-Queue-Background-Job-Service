from datetime import datetime
from uuid import UUID

from src.core.dto import BaseDto
from src.core.enums import EmailStatus


class DeadLetterResponseDto(BaseDto):
    id: UUID
    email_job_id: UUID
    to_email: str
    subject: str
    error: str
    attempts: int
    failed_at: datetime
    replayed: bool
    replayed_at: datetime | None = None


class ReplayResponseDto(BaseDto):
    dead_letter_id: UUID
    email_job_id: UUID
    status: EmailStatus
