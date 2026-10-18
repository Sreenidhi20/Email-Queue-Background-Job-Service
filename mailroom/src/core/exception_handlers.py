import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.errors import AppError, ErrorCatalog, ErrorCode
from src.core.responses import ApiResponse

logger = logging.getLogger(__name__)


class ExceptionHandlers:
    @staticmethod
    def register(app: FastAPI) -> None:
        app.add_exception_handler(AppError, ExceptionHandlers._on_app_error)
        app.add_exception_handler(
            RequestValidationError, ExceptionHandlers._on_validation_error
        )
        app.add_exception_handler(
            StarletteHTTPException, ExceptionHandlers._on_http_error
        )
        app.add_exception_handler(Exception, ExceptionHandlers._on_unhandled)

    @staticmethod
    def _to_json(status_code: int, detail: str, error: str) -> JSONResponse:
        body = ApiResponse.fail(status_code, detail, error)
        return JSONResponse(status_code=status_code, content=body.model_dump(by_alias=True))

    @staticmethod
    async def _on_app_error(_request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, AppError):
            raise exc
        return ExceptionHandlers._to_json(
            exc.status_code, exc.detail, exc.error_text
        )

    @staticmethod
    async def _on_validation_error(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):
            raise exc
        parts = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        return ExceptionHandlers._to_json(
            422,
            "; ".join(parts),
            ErrorCatalog.message_for(ErrorCode.VALIDATION_FAILED),
        )

    @staticmethod
    async def _on_http_error(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        if not isinstance(exc, StarletteHTTPException):
            raise exc
        return ExceptionHandlers._to_json(
            exc.status_code,
            str(exc.detail),
            ErrorCatalog.message_for(ErrorCode.NOT_FOUND),
        )

    @staticmethod
    async def _on_unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled request error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        internal_message = ErrorCatalog.message_for(ErrorCode.INTERNAL)
        return ExceptionHandlers._to_json(
            500, internal_message, internal_message
        )
