from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    EMAIL_JOB_NOT_FOUND = "EMAIL_JOB_NOT_FOUND"
    INVALID_SEND_AT = "INVALID_SEND_AT"
    SEND_AT_TOO_FAR = "SEND_AT_TOO_FAR"
    DEAD_LETTER_NOT_FOUND = "DEAD_LETTER_NOT_FOUND"
    DEAD_LETTER_ALREADY_REPLAYED = "DEAD_LETTER_ALREADY_REPLAYED"
    EMAIL_JOB_NOT_DEAD = "EMAIL_JOB_NOT_DEAD"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    INVALID_API_KEY = "INVALID_API_KEY"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"


class ErrorCatalog:
    _MESSAGES: dict[ErrorCode, str] = {
        ErrorCode.VALIDATION_FAILED: "Request validation failed",
        ErrorCode.NOT_FOUND: "Resource not found",
        ErrorCode.EMAIL_JOB_NOT_FOUND: "Email job not found",
        ErrorCode.INVALID_SEND_AT: "Scheduled time must be in the future",
        ErrorCode.SEND_AT_TOO_FAR: "Scheduled time is too far ahead",
        ErrorCode.DEAD_LETTER_NOT_FOUND: "Dead letter not found",
        ErrorCode.DEAD_LETTER_ALREADY_REPLAYED: "Dead letter was already replayed",
        ErrorCode.EMAIL_JOB_NOT_DEAD: "Email job is no longer dead",
        ErrorCode.SERVICE_UNAVAILABLE: "A dependency is unavailable",
        ErrorCode.QUEUE_UNAVAILABLE: "Email queue is unavailable",
        ErrorCode.INVALID_API_KEY: "Missing or invalid API key",
        ErrorCode.RATE_LIMITED: "Too many requests",
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

    @property
    def headers(self) -> dict[str, str]:
        """Extra HTTP headers for the error response (subclasses may add some)."""
        return {}


class BadRequestError(AppError):
    STATUS_CODE = 400


class ConflictError(AppError):
    STATUS_CODE = 409


class NotFoundError(AppError):
    STATUS_CODE = 404


class ServiceUnavailableError(AppError):
    STATUS_CODE = 503


class UnauthorizedError(AppError):
    STATUS_CODE = 401

    @property
    def headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": "ApiKey"}


class TooManyRequestsError(AppError):
    STATUS_CODE = 429

    def __init__(self, retry_after_seconds: int, detail: str | None = None) -> None:
        super().__init__(ErrorCode.RATE_LIMITED, detail)
        self._retry_after_seconds = retry_after_seconds

    @property
    def retry_after_seconds(self) -> int:
        return self._retry_after_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self._retry_after_seconds)}


class DuplicateKeyError(Exception):
    """An insert lost a race against another request using the same idempotency key."""
