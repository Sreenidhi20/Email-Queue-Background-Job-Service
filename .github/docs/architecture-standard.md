# Architecture Standard: Feature-Sliced, Class-Based FastAPI

Used for **all upcoming projects** (Mailroom first). Same layout, same response contract, same OOP rules every time.

> **Honest note:** this is "DDD-style" (domain folder + feature slices + layers), not full Domain-Driven Design (aggregates, repositories, domain events, bounded contexts). That's fine for our size and it's how your workplace does it. In interviews call it _"feature-sliced layered architecture with a domain layer"_.
> FastAPI examples online use plain functions. Class-based works well too, with two rules: register routes with `add_api_route` (not decorators) and use plain `def` handlers (not `async def`) while we use sync SQLAlchemy.

---

## 1. Folder structure

```
mailroom/
├── src/
│   ├── main.py                          # builds the app, registers routers + error handlers
│   ├── core/                            # shared, framework-level, depends on nothing else
│   │   ├── config.py                    # Settings (env vars)
│   │   ├── database.py                  # Database class, created ONCE, reused everywhere
│   │   ├── enums.py                     # EmailStatus, ...
│   │   ├── errors.py                    # ErrorCode, ErrorCatalog, AppError + subclasses
│   │   ├── exception_handlers.py        # AppError / validation / 500  ->  ApiResponse
│   │   ├── dto.py                       # BaseDto (camelCase), PageDto
│   │   └── responses.py                 # ApiResponse envelope
│   ├── domain/                          # TABLE DEFINITIONS only (column by column)
│   │   ├── base.py                      # SQLAlchemy Base
│   │   └── email_job.py                 # EmailJob table
│   ├── infrastructure/                  # things OUTSIDE our process
│   │   ├── redis.py                     # RedisClient
│   │   └── celery_app.py                # Celery instance
│   └── features/
│       ├── health/
│       │   ├── dto/health_dto.py
│       │   ├── health_service.py
│       │   └── health_router.py
│       └── emails/
│           ├── dto/email_dto.py         # request/response DTOs
│           ├── email_query.py           # DB access (uses domain tables)
│           ├── email_service.py         # business logic (calls the query)
│           ├── email_router.py          # API endpoints (calls the service)
│           └── email_tasks.py           # Celery tasks (only for features with background work)
├── alembic/
├── tests/
├── .env
└── requirements.txt
```

Put an empty `__init__.py` in every folder. Run with `uvicorn src.main:app --reload`.
`email_tasks.py` is the one extra file beyond your list. Only features with background jobs get a `<feature>_tasks.py`.

## 2. Layer rules (the part reviewers care about)

```
Router  ──▶  Service  ──▶  Query  ──▶  Domain (tables)
   │            │            │
   └────────────┴────────────┴──▶  Core (errors, enums, config, DTO base)
                  Service/Tasks ──▶ Infrastructure (Redis, Celery, mailer)
```

| Layer              | Does                                                                                      | Must NOT                                           |
| ------------------ | ----------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Router**         | Defines endpoints, reads request, calls ONE service method, wraps result in `ApiResponse` | Contain logic, touch the DB, raise `HTTPException` |
| **Service**        | Business rules, orchestration, raises `AppError` subclasses                               | Write SQL, know about HTTP/FastAPI                 |
| **Query**          | All DB reads/writes for that feature (SQLAlchemy)                                         | Contain business rules, raise HTTP errors          |
| **Domain**         | Table + column definitions                                                                | Contain logic or imports from features             |
| **Infrastructure** | Talk to Redis / Celery / SMTP                                                             | Know about features                                |
| **Core**           | Shared building blocks                                                                    | Import from any other layer                        |

One service call = one unit of work. Query write methods commit.

---

## 3. The response contract (every endpoint, success or failure)

```json
{
  "statusCode": 200,
  "isSuccess": true,
  "data": [],
  "detail": null,
  "error": null
}
```

| Field        | Meaning                                                                                                   |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| `statusCode` | Same number as the HTTP status                                                                            |
| `isSuccess`  | `true` for 2xx, `false` otherwise                                                                         |
| `data`       | The payload (object, list, or `PageDto`). `null` on failure                                               |
| `detail`     | Our **specific** text for this case, e.g. `"Email job 8f2c... not found"`                                 |
| `error`      | The **catalog text** for the error code from `errors.py`, e.g. `"Email job not found"`. `null` on success |

Examples:

```json
{ "statusCode": 202, "isSuccess": true,
  "data": { "id": "8f2c...", "status": "queued" }, "detail": "Email queued", "error": null }

{ "statusCode": 404, "isSuccess": false, "data": null,
  "detail": "Email job 8f2c... does not exist", "error": "Email job not found" }

{ "statusCode": 422, "isSuccess": false, "data": null,
  "detail": "body.toEmail: value is not a valid email address", "error": "Request validation failed" }
```

Paginated lists use `data: { "items": [], "total": 0, "page": 1, "pageSize": 20 }`.
JSON keys are **camelCase**; Python code stays snake_case (handled by `BaseDto`).

---

## 4. Core

```python
# src/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Mailroom"
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025


settings = Settings()
```

```python
# src/core/enums.py
from enum import Enum


class EmailStatus(str, Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    RETRYING = "retrying"
    DEAD = "dead"
```

```python
# src/core/errors.py
from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    EMAIL_JOB_NOT_FOUND = "EMAIL_JOB_NOT_FOUND"
    INVALID_SEND_AT = "INVALID_SEND_AT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL = "INTERNAL"


class ErrorCatalog:
    """Single place that maps every ErrorCode to its public text."""

    _MESSAGES: dict[ErrorCode, str] = {
        ErrorCode.VALIDATION_FAILED: "Request validation failed",
        ErrorCode.NOT_FOUND: "Resource not found",
        ErrorCode.EMAIL_JOB_NOT_FOUND: "Email job not found",
        ErrorCode.INVALID_SEND_AT: "Scheduled time must be in the future",
        ErrorCode.SERVICE_UNAVAILABLE: "A dependency is unavailable",
        ErrorCode.INTERNAL: "Something went wrong on our side",
    }

    @classmethod
    def message_for(cls, code: ErrorCode) -> str:
        return cls._MESSAGES.get(code, cls._MESSAGES[ErrorCode.INTERNAL])


class AppError(Exception):
    """Base for every error our services raise. Subclasses only fix the HTTP status."""

    STATUS_CODE: int = 500

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        self._code = code
        self._detail = detail
        super().__init__(self.detail)

    @property
    def code(self) -> ErrorCode:
        return self._code

    @property
    def status_code(self) -> int:
        return self.STATUS_CODE

    @property
    def error_text(self) -> str:
        return ErrorCatalog.message_for(self._code)

    @property
    def detail(self) -> str:
        return self._detail or self.error_text


class BadRequestError(AppError):
    STATUS_CODE = 400


class NotFoundError(AppError):
    STATUS_CODE = 404


class ServiceUnavailableError(AppError):
    STATUS_CODE = 503
```

```python
# src/core/dto.py
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class BaseDto(BaseModel):
    """Python uses snake_case, JSON uses camelCase. Works for requests and responses."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class PageDto(BaseDto, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
```

```python
# src/core/responses.py
from typing import Generic

from src.core.dto import BaseDto, T


class ApiResponse(BaseDto, Generic[T]):
    status_code: int
    is_success: bool
    data: T | None = None
    detail: str | None = None
    error: str | None = None

    @classmethod
    def ok(cls, data: T | None = None, status_code: int = 200, detail: str | None = None) -> "ApiResponse[T]":
        return cls(status_code=status_code, is_success=True, data=data, detail=detail, error=None)

    @classmethod
    def fail(cls, status_code: int, detail: str, error: str) -> "ApiResponse[None]":
        return ApiResponse[None](status_code=status_code, is_success=False, data=None, detail=detail, error=error)
```

```python
# src/core/exception_handlers.py
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.errors import AppError, ErrorCatalog, ErrorCode
from src.core.responses import ApiResponse


class ExceptionHandlers:
    """Turns every failure into the ApiResponse envelope."""

    @staticmethod
    def register(app: FastAPI) -> None:
        app.add_exception_handler(AppError, ExceptionHandlers._on_app_error)
        app.add_exception_handler(RequestValidationError, ExceptionHandlers._on_validation_error)
        app.add_exception_handler(StarletteHTTPException, ExceptionHandlers._on_http_error)
        app.add_exception_handler(Exception, ExceptionHandlers._on_unhandled)

    @staticmethod
    def _to_json(status_code: int, detail: str, error: str) -> JSONResponse:
        body = ApiResponse.fail(status_code, detail, error)
        return JSONResponse(status_code=status_code, content=body.model_dump(by_alias=True))

    @staticmethod
    async def _on_app_error(request: Request, exc: AppError) -> JSONResponse:
        return ExceptionHandlers._to_json(exc.status_code, exc.detail, exc.error_text)

    @staticmethod
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return ExceptionHandlers._to_json(
            422, "; ".join(parts), ErrorCatalog.message_for(ErrorCode.VALIDATION_FAILED)
        )

    @staticmethod
    async def _on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # e.g. unknown route -> 404
        return ExceptionHandlers._to_json(
            exc.status_code, str(exc.detail), ErrorCatalog.message_for(ErrorCode.NOT_FOUND)
        )

    @staticmethod
    async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # never leak internals: log `exc` here, return generic text
        return ExceptionHandlers._to_json(
            500, ErrorCatalog.message_for(ErrorCode.INTERNAL), ErrorCatalog.message_for(ErrorCode.INTERNAL)
        )
```

```python
# src/core/database.py
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings


class Database:
    """Created ONCE at import time (see `db` below) and reused everywhere."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: Engine = create_engine(url, echo=echo, pool_pre_ping=True)
        self._session_factory = sessionmaker(
            bind=self._engine, autoflush=False, expire_on_commit=False
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def get_session(self) -> Iterator[Session]:
        """FastAPI dependency: one session per request."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """For code outside a request (Celery tasks, scripts)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def ping(self) -> bool:
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def dispose(self) -> None:
        self._engine.dispose()


db = Database(settings.DATABASE_URL)
```

## 5. Domain (table definitions, column by column)

```python
# src/domain/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# src/domain/email_job.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import EmailStatus
from src.domain.base import Base


class EmailJob(Base):
    __tablename__ = "email_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EmailStatus] = mapped_column(
        SAEnum(EmailStatus, name="email_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=EmailStatus.QUEUED,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Alembic's `env.py` imports `Base` from `src.domain.base` and every model file in `src/domain/`, so autogenerate sees them.

## 6. Infrastructure (external systems)

```python
# src/infrastructure/redis.py
import redis

from src.core.config import settings


class RedisClient:
    """Wraps the external Redis server. Created once, reused everywhere."""

    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(url, decode_responses=True)

    @property
    def client(self) -> redis.Redis:
        return self._client

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except redis.RedisError:
            return False

    def close(self) -> None:
        self._client.close()


redis_client = RedisClient(settings.REDIS_URL)
```

```python
# src/infrastructure/celery_app.py
from celery import Celery

from src.core.config import settings

celery_app = Celery(
    "mailroom",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.features.emails.email_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
```

Run the worker with `celery -A src.infrastructure.celery_app worker --loglevel=info --pool=solo` (`--pool=solo` on Windows only).

---

## 7. A feature, end to end: `emails`

### 7.1 DTOs

```python
# src/features/emails/dto/email_dto.py
from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from src.core.dto import BaseDto
from src.core.enums import EmailStatus


class CreateEmailRequestDto(BaseDto):
    to_email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    send_at: datetime | None = None          # present = delayed job


class EmailJobResponseDto(BaseDto):
    id: UUID
    to_email: str
    subject: str
    status: EmailStatus
    attempts: int
    last_error: str | None = None
    scheduled_for: datetime | None = None
    created_at: datetime
    sent_at: datetime | None = None
```

### 7.2 Query (DB only)

```python
# src/features/emails/email_query.py
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.enums import EmailStatus
from src.domain.email_job import EmailJob


class EmailQuery:
    """All database access for the emails feature. No business rules here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: EmailJob) -> EmailJob:
        self._session.add(job)
        return self._commit(job)

    def save(self, job: EmailJob) -> EmailJob:
        return self._commit(job)

    def get_by_id(self, job_id: UUID) -> EmailJob | None:
        return self._session.get(EmailJob, job_id)

    def get_by_idempotency_key(self, key: str) -> EmailJob | None:
        stmt = select(EmailJob).where(EmailJob.idempotency_key == key)
        return self._session.scalars(stmt).first()

    def list_paginated(
        self, status: EmailStatus | None, page: int, page_size: int
    ) -> tuple[list[EmailJob], int]:
        stmt = select(EmailJob)
        count_stmt = select(func.count()).select_from(EmailJob)
        if status is not None:
            stmt = stmt.where(EmailJob.status == status)
            count_stmt = count_stmt.where(EmailJob.status == status)

        total = self._session.scalar(count_stmt) or 0
        rows = self._session.scalars(
            stmt.order_by(EmailJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), total

    def _commit(self, job: EmailJob) -> EmailJob:        # private helper
        self._session.commit()
        self._session.refresh(job)
        return job
```

### 7.3 Tasks (thin; real logic is added in Mailroom Steps 2 to 4)

```python
# src/features/emails/email_tasks.py
from src.infrastructure.celery_app import celery_app


@celery_app.task(name="emails.send")
def send_email_task(job_id: str) -> str:
    # Step 2: open db.session_scope(), load the job via EmailQuery, send via mailer,
    # update status. Tasks stay thin: build the objects, call ONE method.
    return job_id
```

### 7.4 Service (business logic)

```python
# src/features/emails/email_service.py
from datetime import datetime, timezone
from uuid import UUID

from celery import Task

from src.core.dto import PageDto
from src.core.enums import EmailStatus
from src.core.errors import BadRequestError, ErrorCode, NotFoundError
from src.domain.email_job import EmailJob
from src.features.emails.dto.email_dto import CreateEmailRequestDto, EmailJobResponseDto
from src.features.emails.email_query import EmailQuery
from src.features.emails.email_tasks import send_email_task


class EmailService:
    """Business rules for emails. Knows nothing about HTTP or SQL."""

    DEFAULT_MAX_ATTEMPTS = 5           # public class constant
    _MAX_PAGE_SIZE = 100               # internal class constant

    def __init__(
        self,
        query: EmailQuery,
        send_task: Task = send_email_task,        # injected, so tests can pass a fake
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._query = query
        self._send_task = send_task
        self._max_attempts = self.DEFAULT_MAX_ATTEMPTS
        self.max_attempts = max_attempts          # goes through the setter (validated)

    # ---- properties (getter / setter) ------------------------------------
    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @max_attempts.setter
    def max_attempts(self, value: int) -> None:
        if not 1 <= value <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        self._max_attempts = value

    # ---- public API (what the router calls) ------------------------------
    def create(self, dto: CreateEmailRequestDto, idempotency_key: str | None = None) -> EmailJobResponseDto:
        if idempotency_key:
            existing = self._query.get_by_idempotency_key(idempotency_key)
            if existing is not None:                       # client retried: same job, no 2nd email
                return EmailJobResponseDto.model_validate(existing)

        send_at = self._normalize_utc(dto.send_at)
        self._ensure_in_future(send_at)

        job = self._query.add(self._build_job(dto, send_at, idempotency_key))   # commit BEFORE enqueue
        self._enqueue(job)
        return EmailJobResponseDto.model_validate(job)

    def get(self, job_id: UUID) -> EmailJobResponseDto:
        return EmailJobResponseDto.model_validate(self._get_or_raise(job_id))

    def list(self, status: EmailStatus | None, page: int, page_size: int) -> PageDto[EmailJobResponseDto]:
        size = min(page_size, self._MAX_PAGE_SIZE)
        rows, total = self._query.list_paginated(status, page, size)
        items = [EmailJobResponseDto.model_validate(r) for r in rows]
        return PageDto[EmailJobResponseDto](items=items, total=total, page=page, page_size=size)

    # ---- private helpers ---------------------------------------------------
    def _get_or_raise(self, job_id: UUID) -> EmailJob:
        job = self._query.get_by_id(job_id)
        if job is None:
            raise NotFoundError(ErrorCode.EMAIL_JOB_NOT_FOUND, f"Email job {job_id} does not exist")
        return job

    def _build_job(self, dto: CreateEmailRequestDto, send_at: datetime | None, key: str | None) -> EmailJob:
        return EmailJob(
            to_email=str(dto.to_email),
            subject=dto.subject,
            body=dto.body,
            status=EmailStatus.QUEUED,
            attempts=0,
            max_attempts=self._max_attempts,
            scheduled_for=send_at,
            idempotency_key=key,
        )

    def _enqueue(self, job: EmailJob) -> None:
        result = self._send_task.apply_async(args=[str(job.id)], eta=job.scheduled_for)
        job.celery_task_id = result.id
        self._query.save(job)

    @staticmethod
    def _normalize_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _ensure_in_future(send_at: datetime | None) -> None:
        if send_at is not None and send_at <= datetime.now(timezone.utc):
            raise BadRequestError(ErrorCode.INVALID_SEND_AT, "sendAt must be a future date and time")

    def __repr__(self) -> str:
        return f"EmailService(max_attempts={self._max_attempts})"
```

### 7.5 Router (API definition)

```python
# src/features/emails/email_router.py
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from src.core.database import db
from src.core.dto import PageDto
from src.core.enums import EmailStatus
from src.core.responses import ApiResponse
from src.features.emails.dto.email_dto import CreateEmailRequestDto, EmailJobResponseDto
from src.features.emails.email_query import EmailQuery
from src.features.emails.email_service import EmailService


def get_email_service(session: Session = Depends(db.get_session)) -> EmailService:
    """Composition root for this feature: session -> query -> service."""
    return EmailService(EmailQuery(session))


class EmailRouter:
    """Only defines the API. Every handler: read input, call ONE service method, wrap in ApiResponse."""

    def __init__(self) -> None:
        self._router = APIRouter(prefix="/emails", tags=["Emails"])
        self._register_routes()

    @property
    def router(self) -> APIRouter:
        return self._router

    def _register_routes(self) -> None:
        self._router.add_api_route(
            "", self._create_email, methods=["POST"], status_code=202,
            response_model=ApiResponse[EmailJobResponseDto], summary="Queue an email",
        )
        self._router.add_api_route(
            "", self._list_emails, methods=["GET"],
            response_model=ApiResponse[PageDto[EmailJobResponseDto]], summary="List email jobs",
        )
        self._router.add_api_route(
            "/{job_id}", self._get_email, methods=["GET"],
            response_model=ApiResponse[EmailJobResponseDto], summary="Get one email job",
        )

    # plain `def` (not async): sync SQLAlchemy runs in FastAPI's threadpool
    def _create_email(
        self,
        body: CreateEmailRequestDto,
        idempotency_key: str | None = Header(default=None),
        service: EmailService = Depends(get_email_service),
    ) -> ApiResponse[EmailJobResponseDto]:
        return ApiResponse.ok(service.create(body, idempotency_key), status_code=202, detail="Email queued")

    def _list_emails(
        self,
        status: EmailStatus | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
        service: EmailService = Depends(get_email_service),
    ) -> ApiResponse[PageDto[EmailJobResponseDto]]:
        return ApiResponse.ok(service.list(status, page, page_size))

    def _get_email(
        self, job_id: UUID, service: EmailService = Depends(get_email_service)
    ) -> ApiResponse[EmailJobResponseDto]:
        return ApiResponse.ok(service.get(job_id))
```

### 7.6 Health feature (no table, so no query layer)

```python
# src/features/health/dto/health_dto.py
from src.core.dto import BaseDto


class HealthResponseDto(BaseDto):
    database: bool
    redis: bool
```

```python
# src/features/health/health_service.py
from src.core.database import Database, db
from src.core.errors import ErrorCode, ServiceUnavailableError
from src.features.health.dto.health_dto import HealthResponseDto
from src.infrastructure.redis import RedisClient, redis_client


class HealthService:
    def __init__(self, database: Database = db, redis: RedisClient = redis_client) -> None:
        self._database = database
        self._redis = redis

    def check(self) -> HealthResponseDto:
        result = HealthResponseDto(database=self._database.ping(), redis=self._redis.ping())
        if not (result.database and result.redis):
            raise ServiceUnavailableError(
                ErrorCode.SERVICE_UNAVAILABLE, f"database={result.database}, redis={result.redis}"
            )
        return result
```

```python
# src/features/health/health_router.py
from fastapi import APIRouter

from src.core.responses import ApiResponse
from src.features.health.dto.health_dto import HealthResponseDto
from src.features.health.health_service import HealthService


class HealthRouter:
    def __init__(self, service: HealthService | None = None) -> None:
        self._service = service or HealthService()
        self._router = APIRouter(tags=["Health"])
        self._router.add_api_route(
            "/health", self._health, methods=["GET"], response_model=ApiResponse[HealthResponseDto]
        )

    @property
    def router(self) -> APIRouter:
        return self._router

    def _health(self) -> ApiResponse[HealthResponseDto]:
        return ApiResponse.ok(self._service.check())
```

## 8. `main.py`: register everything in one place

```python
# src/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.core.config import settings
from src.core.database import db
from src.core.exception_handlers import ExceptionHandlers
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
    async def _lifespan(self, app: FastAPI):
        yield                                   # shutdown cleanup below
        db.dispose()
        redis_client.close()

    def _register_routers(self) -> None:
        for router in (HealthRouter().router, EmailRouter().router):
            self._app.include_router(router)


app = Application().app
```

Adding a feature = create its folder, then add its router to that tuple. Nothing else changes.

---

## 9. Class-based rules (follow through every project)

**1. Everything with behaviour is a class.** Router, Service, Query, Settings, Database, clients, handlers. DTOs are Pydantic classes. Table definitions are SQLAlchemy classes. Tiny pure helpers can stay as module functions.

**2. Constructor injection, always.** A class receives what it needs in `__init__` and never creates its own dependencies inside methods.
`EmailService(query, send_task)` can then be tested with a fake query and a fake task.

**3. Visibility (Python has conventions, not hard walls):**

| Syntax         | Use for                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| `name`         | Public API: what other layers may call                                                                 |
| `_name`        | Private by convention: internal attributes and helper methods. **Our default for anything not public** |
| `__name`       | Name-mangled (becomes `_Class__name`). Only when a subclass must not accidentally override it. Rare    |
| `NAME` (UPPER) | Class constants. `_NAME` for internal ones                                                             |

**4. Attributes are private, access through properties when there is a reason.** Use `@property` plus a setter when you need validation, a derived value, or a read-only view. Don't write getters/setters for plain data, because they add noise.

```python
@property
def max_attempts(self) -> int: ...          # getter
@max_attempts.setter
def max_attempts(self, value: int) -> None: ...   # setter with validation
```

Read-only = property with no setter.

**5. Method kinds:**

- instance method: uses `self`, which is the default
- `@classmethod`: alternate constructors or class-level data (`ApiResponse.ok`, `ErrorCatalog.message_for`)
- `@staticmethod`: pure helper that doesn't need `self` (`_normalize_utc`)

**6. Constructor order** in a class: class constants, `__init__`, properties, public methods, private helpers, dunder methods (`__repr__`).

**7. Type hints on every parameter and return.** DTOs for anything crossing a layer boundary: routers receive and return DTOs, services return DTOs, queries return domain objects.

**8. Errors:** services raise `AppError` subclasses with an `ErrorCode` and optional detail. Nobody else formats errors. Handlers do.

**9. One singleton per external resource**, created at module import: `db` (database.py), `redis_client` (redis.py), `celery_app`. Everyone imports that one instance.

## 10. Naming conventions

| Thing       | Convention                          | Example                                        |
| ----------- | ----------------------------------- | ---------------------------------------------- |
| Files       | `snake_case`, prefixed by feature   | `email_service.py`                             |
| Classes     | `PascalCase`, role suffix           | `EmailService`, `EmailQuery`, `EmailRouter`    |
| DTOs        | `...Dto`                            | `CreateEmailRequestDto`, `EmailJobResponseDto` |
| Tables      | plural snake_case                   | `email_jobs`                                   |
| Enums       | `PascalCase` class, `UPPER` members | `EmailStatus.QUEUED`                           |
| Error codes | `UPPER_SNAKE`                       | `EMAIL_JOB_NOT_FOUND`                          |
| JSON keys   | camelCase (automatic)               | `statusCode`, `pageSize`                       |

## 11. New-feature checklist

1. Table needed? Add `src/domain/<thing>.py` and an Alembic migration.
2. Add any new enum to `core/enums.py` and any new errors to `core/errors.py` (code **and** catalog text).
3. `features/<name>/dto/<name>_dto.py`: request and response DTOs.
4. `<name>_query.py`: DB methods.
5. `<name>_service.py`: business rules; raises `AppError`s.
6. `<name>_router.py`: class with `_register_routes`; handlers return `ApiResponse`.
7. Register the router in `main.py`.
8. Tests: service with a fake query; router with `TestClient`.

## 12. Request flow: `POST /emails`

```
Client ──▶ EmailRouter._create_email      (validates body into CreateEmailRequestDto)
            └▶ EmailService.create        (idempotency check, future-date rule, build EmailJob)
                 ├▶ EmailQuery.add        (INSERT ... COMMIT, status=queued)
                 └▶ send_email_task.apply_async  (pushes job id to Redis)
            ◀── EmailJobResponseDto
        ◀── ApiResponse { statusCode: 202, isSuccess: true, data: {...} }

Worker ──▶ send_email_task(job_id) ──▶ load row, send, update status (Mailroom Step 2+)
```

## 13. What changes in the Mailroom plan

- `app/` becomes `src/` with the layout above.
- Celery instance: `app/worker/celery_app.py` becomes `src/infrastructure/celery_app.py`.
- `mailer.py` (SMTP locally, HTTP API in production) goes in `src/infrastructure/mailer.py` as a `Mailer` class.
- Tables: `EmailJob` now, `DeadLetter` in `src/domain/dead_letter.py` at Step 6.
- Run commands: `uvicorn src.main:app --reload` and `celery -A src.infrastructure.celery_app worker --loglevel=info --pool=solo`.
- **Step 1** is the same idea (Redis up, one task round trip). Use the files in sections 4, 6 and 8; the `ping` task is replaced by `send_email_task`, which returns its argument.
- Needed packages: `pip install fastapi "uvicorn[standard]" sqlalchemy alembic "psycopg[binary]" pydantic-settings "pydantic[email]" "celery[redis]" flower jinja2`
