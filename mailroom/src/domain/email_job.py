import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import EmailStatus
from src.domain.base import Base


def _email_status_values(statuses: Iterable[EmailStatus]) -> list[str]:
    return [status.value for status in statuses]


class EmailJob(Base):
    __tablename__ = "email_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EmailStatus] = mapped_column(
        SAEnum(
            EmailStatus,
            name="email_status",
            values_callable=_email_status_values,
        ),
        nullable=False,
        default=EmailStatus.QUEUED,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
