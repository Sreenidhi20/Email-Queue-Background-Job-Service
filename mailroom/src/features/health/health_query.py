from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.domain.health_check import HealthCheck


class HealthQuery:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, database_healthy: bool, redis_healthy: bool) -> HealthCheck:
        check = HealthCheck(
            database_healthy=database_healthy,
            redis_healthy=redis_healthy,
        )
        self._session.add(check)
        try:
            self._session.commit()
            self._session.refresh(check)
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return check
