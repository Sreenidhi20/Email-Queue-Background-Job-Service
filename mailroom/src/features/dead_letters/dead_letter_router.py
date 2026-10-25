from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.core.database import db
from src.core.dto import PageDto
from src.core.responses import ApiResponse
from src.features.dead_letters.dead_letter_query import DeadLetterQuery
from src.features.dead_letters.dead_letter_service import DeadLetterService
from src.features.dead_letters.dto.dead_letter_dto import (
    DeadLetterResponseDto,
    ReplayResponseDto,
)
from src.infrastructure.celery_task_publisher import CeleryTaskPublisher


def get_dead_letter_service(
    session: Session = Depends(db.get_session),
) -> DeadLetterService:
    return DeadLetterService(
        DeadLetterQuery(session),
        CeleryTaskPublisher("emails.send"),
    )


class DeadLetterRouter:
    def __init__(self) -> None:
        self._router = APIRouter(prefix="/dead-letters", tags=["Dead letters"])
        self._register_routes()

    @property
    def router(self) -> APIRouter:
        return self._router

    def _register_routes(self) -> None:
        self._router.add_api_route(
            "",
            self._list_dead_letters,
            methods=["GET"],
            response_model=ApiResponse[PageDto[DeadLetterResponseDto]],
            summary="List dead letters",
        )
        self._router.add_api_route(
            "/{letter_id}",
            self._get_dead_letter,
            methods=["GET"],
            response_model=ApiResponse[DeadLetterResponseDto],
            summary="Get one dead letter",
        )
        self._router.add_api_route(
            "/{letter_id}/replay",
            self._replay,
            methods=["POST"],
            status_code=202,
            response_model=ApiResponse[ReplayResponseDto],
            summary="Re-queue a dead email",
        )

    def _list_dead_letters(
        self,
        replayed: bool | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
        service: DeadLetterService = Depends(get_dead_letter_service),
    ) -> ApiResponse[PageDto[DeadLetterResponseDto]]:
        return ApiResponse[PageDto[DeadLetterResponseDto]].ok(
            service.list(replayed, page, page_size)
        )

    def _get_dead_letter(
        self,
        letter_id: UUID,
        service: DeadLetterService = Depends(get_dead_letter_service),
    ) -> ApiResponse[DeadLetterResponseDto]:
        return ApiResponse[DeadLetterResponseDto].ok(service.get(letter_id))

    def _replay(
        self,
        letter_id: UUID,
        service: DeadLetterService = Depends(get_dead_letter_service),
    ) -> ApiResponse[ReplayResponseDto]:
        return ApiResponse[ReplayResponseDto].ok(
            service.replay(letter_id),
            status_code=202,
            detail="Email re-queued",
        )
