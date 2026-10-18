from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from src.core.errors import ErrorCode, ServiceUnavailableError
from src.domain.health_check import HealthCheck
from src.features.health.dto.health_dto import HealthResponseDto


class HealthQueryPort(Protocol):
    def add(self, database_healthy: bool, redis_healthy: bool) -> HealthCheck: ...


class HealthProbe(Protocol):
    def ping(self) -> bool: ...


class HealthService:
    def __init__(
        self,
        query: HealthQueryPort,
        database: HealthProbe,
        redis: HealthProbe,
    ) -> None:
        self._query = query
        self._database = database
        self._redis = redis

    def check(self) -> HealthResponseDto:
        database_healthy = self._database.ping()
        redis_healthy = self._redis.ping()

        if not database_healthy:
            raise self._unavailable(database_healthy, redis_healthy)

        try:
            check = self._query.add(database_healthy, redis_healthy)
        except SQLAlchemyError as error:
            raise self._unavailable(False, redis_healthy) from error

        if not redis_healthy:
            raise self._unavailable(database_healthy, redis_healthy)

        return self._to_dto(check)

    @staticmethod
    def _to_dto(check: HealthCheck) -> HealthResponseDto:
        return HealthResponseDto(
            database=check.database_healthy,
            redis=check.redis_healthy,
            checked_at=check.checked_at,
        )

    @staticmethod
    def _unavailable(database_healthy: bool, redis_healthy: bool) -> ServiceUnavailableError:
        return ServiceUnavailableError(
            ErrorCode.SERVICE_UNAVAILABLE,
            f"database={database_healthy}, redis={redis_healthy}",
        )
