from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from src.core.dto import BaseDto
from src.core.enums import EmailStatus


class CreateEmailRequestDto(BaseDto):
    to_email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    send_at: datetime | None = None


class EmailJobResponseDto(BaseDto):
    id: UUID
    to_email: str
    subject: str
    status: EmailStatus
    attempts: int
    last_error: str | None = None
    scheduled_for: datetime | None = None
    created_at: datetime
    sent_at: datetime | None = None
