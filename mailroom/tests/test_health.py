import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.core.errors import ServiceUnavailableError
from src.domain.base import Base
from src.domain.health_check import HealthCheck
from src.features.health.health_query import HealthQuery
from src.features.health.health_service import HealthService


class FakeDatabase:
    def __init__(self, healthy: bool) -> None:
        self.healthy = healthy

    def ping(self) -> bool:
        return self.healthy


class FakeRedis:
    def __init__(self, healthy: bool) -> None:
        self.healthy = healthy

    def ping(self) -> bool:
        return self.healthy


class FakeHealthQuery:
    def __init__(self) -> None:
        self.recorded: tuple[bool, bool] | None = None

    def add(self, database_healthy: bool, redis_healthy: bool) -> HealthCheck:
        self.recorded = (database_healthy, redis_healthy)
        return HealthCheck(
            id=1,
            database_healthy=database_healthy,
            redis_healthy=redis_healthy,
            checked_at=datetime.now(timezone.utc),
        )


class HealthQueryTests(unittest.TestCase):
    def test_add_persists_health_check(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                check = HealthQuery(session).add(True, True)
                saved = session.scalar(
                    select(HealthCheck).where(HealthCheck.id == check.id)
                )
                if saved is None:
                    self.fail("Health check was not persisted")
                self.assertTrue(saved.database_healthy)
                self.assertTrue(saved.redis_healthy)
                self.assertIsNotNone(saved.checked_at)
        finally:
            engine.dispose()


class HealthServiceTests(unittest.TestCase):
    def test_returns_and_records_healthy_dependencies(self) -> None:
        query = FakeHealthQuery()
        service = HealthService(query, FakeDatabase(True), FakeRedis(True))

        result = service.check()

        self.assertTrue(result.database)
        self.assertTrue(result.redis)
        self.assertEqual(query.recorded, (True, True))

    def test_records_redis_failure_then_raises_unavailable(self) -> None:
        query = FakeHealthQuery()
        service = HealthService(query, FakeDatabase(True), FakeRedis(False))

        with self.assertRaises(ServiceUnavailableError) as raised:
            service.check()

        self.assertEqual(query.recorded, (True, False))
        self.assertIn("redis=False", raised.exception.detail)

    def test_database_failure_raises_without_querying_health_table(self) -> None:
        query = FakeHealthQuery()
        service = HealthService(query, FakeDatabase(False), FakeRedis(True))

        with self.assertRaises(ServiceUnavailableError) as raised:
            service.check()

        self.assertIsNone(query.recorded)
        self.assertIn("database=False", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
