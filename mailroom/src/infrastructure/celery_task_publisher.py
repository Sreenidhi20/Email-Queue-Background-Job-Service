from datetime import datetime

from src.infrastructure.celery_app import celery_app


class CeleryTaskPublisher:
    """Publishes a named task without leaking Celery's untyped result into services."""

    def __init__(self, task_name: str) -> None:
        self._task_name = task_name

    def apply_async(self, *, args: list[str], eta: datetime | None) -> str:
        result = celery_app.send_task(  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
            self._task_name,
            args=args,
            eta=eta,
        )
        task_id = result.id  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(task_id, str):
            raise RuntimeError("Celery did not return a task ID")
        return task_id
