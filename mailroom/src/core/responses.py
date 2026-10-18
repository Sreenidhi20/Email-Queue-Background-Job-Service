from typing import Generic

from src.core.dto import BaseDto, T


class ApiResponse(BaseDto, Generic[T]):
    status_code: int
    is_success: bool
    data: T | None = None
    detail: str | None = None
    error: str | None = None

    @classmethod
    def ok(
        cls, data: T | None = None, status_code: int = 200, detail: str | None = None
    ) -> "ApiResponse[T]":
        return cls(
            status_code=status_code,
            is_success=True,
            data=data,
            detail=detail,
            error=None,
        )

    @classmethod
    def fail(cls, status_code: int, detail: str, error: str) -> "ApiResponse[None]":
        return ApiResponse[None](
            status_code=status_code,
            is_success=False,
            data=None,
            detail=detail,
            error=error,
        )
