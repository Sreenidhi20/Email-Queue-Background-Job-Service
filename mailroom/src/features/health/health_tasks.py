import time

from src.infrastructure.celery_app import celery_app


@celery_app.task(  # type: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    name="ping"
)
def ping(message: str) -> str:
    time.sleep(3)
    return f"pong: {message}"
