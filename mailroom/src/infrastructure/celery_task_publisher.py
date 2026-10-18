from datetime import datetime

from kombu.exceptions import OperationalError  # type: ignore[reportMissingTypeStubs]

from src.core.errors import ErrorCode, ServiceUnavailableError
from src.infrastructure.celery_app import celery_app


class CeleryTaskPublisher:
    """Publishes a named task without leaking Celery's untyped result into services."""

    def __init__(self, task_name: str) -> None:
        self._task_name = task_name

    def apply_async(self, *, args: list[str], eta: datetime | None) -> str:
        try:
            result = celery_app.send_task(  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
                self._task_name,
                args=args,
                eta=eta,
                ignore_result=True,  # job state lives in the database
            )
        except (OperationalError, OSError) as error:
            raise ServiceUnavailableError(
                ErrorCode.QUEUE_UNAVAILABLE,
                "The queue (Redis) could not be reached; the email was not queued",
            ) from error
        task_id = result.id  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(task_id, str):
            raise RuntimeError("Celery did not return a task ID")
        return task_id
