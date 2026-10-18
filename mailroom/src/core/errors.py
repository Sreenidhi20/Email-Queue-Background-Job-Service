from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    EMAIL_JOB_NOT_FOUND = "EMAIL_JOB_NOT_FOUND"
    INVALID_SEND_AT = "INVALID_SEND_AT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL = "INTERNAL"


class ErrorCatalog:
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
    STATUS_CODE = 500

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
