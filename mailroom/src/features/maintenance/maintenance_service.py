from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from src.core.enums import EmailStatus
from src.features.emails.dto.email_dto import (
    CreateEmailRequestDto,
    EmailJobResponseDto,
)
from src.features.maintenance.dto.maintenance_dto import DigestStatsDto


class MaintenanceQueryPort(Protocol):
    def delete_sent_before(self, cutoff: datetime) -> int: ...

    def count_sent_since(self, since: datetime) -> int: ...

    def count_dead_since(self, since: datetime) -> int: ...

    def count_with_status(self, status: EmailStatus) -> int: ...

    def count_unreplayed_dead_letters(self) -> int: ...


class EmailSubmitter(Protocol):
    def create(
        self, dto: CreateEmailRequestDto, idempotency_key: str | None = None
    ) -> EmailJobResponseDto: ...


class MaintenanceService:
    """Logic behind the scheduled jobs. The digest goes through the normal email
    queue, so it gets retries, dead-lettering and replay like any other email."""

    DEFAULT_RETENTION_DAYS = 30

    def __init__(
        self,
        query: MaintenanceQueryPort,
        email_submitter: EmailSubmitter,
        digest_to: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._query = query
        self._email_submitter = email_submitter
        self._digest_to = digest_to
        self._retention_days = self.DEFAULT_RETENTION_DAYS
        self.retention_days = retention_days

    @property
    def retention_days(self) -> int:
        return self._retention_days

    @retention_days.setter
    def retention_days(self, value: int) -> None:
        if not 1 <= value <= 365:
            raise ValueError("retention_days must be between 1 and 365")
        self._retention_days = value

    @property
    def digest_to(self) -> str | None:
        return self._digest_to

    def cleanup_sent_jobs(self, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=self._retention_days)
        return self._query.delete_sent_before(cutoff)

    def send_daily_digest(self, now: datetime | None = None) -> str:
        if not self._digest_to:
            return "skipped: DIGEST_TO_EMAIL is not set"
        moment = now or datetime.now(timezone.utc)
        stats = self._collect_stats(moment - timedelta(hours=24))
        subject, body = self._build_message(stats, moment.date())
        self._email_submitter.create(
            CreateEmailRequestDto(to_email=self._digest_to, subject=subject, body=body),
            idempotency_key=f"daily-digest-{moment.date().isoformat()}",
        )
        return "queued"

    def _collect_stats(self, since: datetime) -> DigestStatsDto:
        return DigestStatsDto(
            sent_last_24h=self._query.count_sent_since(since),
            dead_last_24h=self._query.count_dead_since(since),
            queued_now=self._query.count_with_status(EmailStatus.QUEUED),
            retrying_now=self._query.count_with_status(EmailStatus.RETRYING),
            unreplayed_dead_letters=self._query.count_unreplayed_dead_letters(),
        )

    @staticmethod
    def _build_message(stats: DigestStatsDto, day: date) -> tuple[str, str]:
        subject = f"Mailroom daily digest {day.isoformat()}"
        body = "\n".join(
            [
                "Mailroom summary for the last 24 hours (UTC):",
                "",
                f"Sent:                    {stats.sent_last_24h}",
                f"Failed permanently:      {stats.dead_last_24h}",
                f"Queued right now:        {stats.queued_now}",
                f"Retrying right now:      {stats.retrying_now}",
                f"Dead letters to review:  {stats.unreplayed_dead_letters}",
            ]
        )
        return subject, body
