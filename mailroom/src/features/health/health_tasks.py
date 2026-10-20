import time

from src.infrastructure.celery_app import celery_app


@celery_app.task(  # type: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    name="ping",
    ignore_result=False,  # the smoke test reads the result
)
def ping(message: str) -> str:
    time.sleep(3)
    return f"pong: {message}"
