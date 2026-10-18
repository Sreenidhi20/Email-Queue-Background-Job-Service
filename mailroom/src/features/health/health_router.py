from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.core.database import db
from src.core.responses import ApiResponse
from src.features.health.dto.health_dto import HealthResponseDto
from src.features.health.health_query import HealthQuery
from src.features.health.health_service import HealthService
from src.infrastructure.redis import redis_client


def get_health_service(
    session: Session = Depends(db.get_session),
) -> HealthService:
    return HealthService(HealthQuery(session), db, redis_client)


class HealthRouter:
    def __init__(self) -> None:
        self._router = APIRouter(tags=["Health"])
        self._register_routes()

    @property
    def router(self) -> APIRouter:
        return self._router

    def _register_routes(self) -> None:
        self._router.add_api_route(
            "/health",
            self._health,
            methods=["GET"],
            response_model=ApiResponse[HealthResponseDto],
        )

    def _health(
        self,
        service: HealthService = Depends(get_health_service),
    ) -> ApiResponse[HealthResponseDto]:
        return ApiResponse[HealthResponseDto].ok(service.check())
