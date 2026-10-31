from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import db
from src.core.dto import PageDto
from src.core.enums import EmailStatus
from src.core.responses import ApiResponse
from src.core.security import api_key_auth
from src.features.emails.dto.email_dto import (
    CreateEmailRequestDto,
    EmailJobResponseDto,
)
from src.features.emails.email_query import EmailQuery
from src.features.emails.email_service import EmailService
from src.infrastructure.celery_task_publisher import CeleryTaskPublisher
from src.infrastructure.rate_limiter import create_email_rate_limit


def get_email_service(
    session: Session = Depends(db.get_session),
) -> EmailService:
    return EmailService(
        EmailQuery(session),
        CeleryTaskPublisher("emails.send"),
        max_send_ahead_days=settings.MAX_SEND_AHEAD_DAYS,
    )


class EmailRouter:
    def __init__(self) -> None:
        self._router = APIRouter(
            prefix="/emails",
            tags=["Emails"],
            dependencies=[Depends(api_key_auth)],
        )
        self._register_routes()

    @property
    def router(self) -> APIRouter:
        return self._router

    def _register_routes(self) -> None:
        self._router.add_api_route(
            "",
            self._create_email,
            methods=["POST"],
            status_code=202,
            dependencies=[Depends(create_email_rate_limit)],
            response_model=ApiResponse[EmailJobResponseDto],
            summary="Queue an email",
        )
        self._router.add_api_route(
            "",
            self._list_emails,
            methods=["GET"],
            response_model=ApiResponse[PageDto[EmailJobResponseDto]],
            summary="List email jobs",
        )
        self._router.add_api_route(
            "/{job_id}",
            self._get_email,
            methods=["GET"],
            response_model=ApiResponse[EmailJobResponseDto],
            summary="Get one email job",
        )

    def _create_email(
        self,
        body: CreateEmailRequestDto,
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=100
        ),
        service: EmailService = Depends(get_email_service),
    ) -> ApiResponse[EmailJobResponseDto]:
        return ApiResponse[EmailJobResponseDto].ok(
            service.create(body, idempotency_key),
            status_code=202,
            detail="Email queued",
        )

    def _list_emails(
        self,
        status: EmailStatus | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
        service: EmailService = Depends(get_email_service),
    ) -> ApiResponse[PageDto[EmailJobResponseDto]]:
        return ApiResponse[PageDto[EmailJobResponseDto]].ok(
            service.list(status, page, page_size)
        )

    def _get_email(
        self,
        job_id: UUID,
        service: EmailService = Depends(get_email_service),
    ) -> ApiResponse[EmailJobResponseDto]:
        return ApiResponse[EmailJobResponseDto].ok(service.get(job_id))
