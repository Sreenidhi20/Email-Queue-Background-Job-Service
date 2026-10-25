from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from src.core.config import settings
from src.core.database import db
from src.core.exception_handlers import ExceptionHandlers
from src.features.dead_letters.dead_letter_router import DeadLetterRouter
from src.features.emails.email_router import EmailRouter
from src.features.health.health_router import HealthRouter
from src.infrastructure.redis import redis_client


class Application:
    def __init__(self) -> None:
        self._app = FastAPI(title=settings.APP_NAME, lifespan=self._lifespan)
        ExceptionHandlers.register(self._app)
        self._register_routers()

    @property
    def app(self) -> FastAPI:
        return self._app

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        yield
        db.dispose()
        redis_client.close()

    def _register_routers(self) -> None:
        for router in (
            HealthRouter().router,
            EmailRouter().router,
            DeadLetterRouter().router,
        ):
            self._app.include_router(router)


app = Application().app
__all__ = ["app"]
