import random

from src.core.config import settings


class RetryPolicy:
    """Exponential backoff with jitter: base * 2^n, capped, then randomised."""

    _MAX_EXPONENT = 30

    def __init__(
        self,
        base_seconds: int,
        max_seconds: int,
        jitter: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        if base_seconds < 1 or max_seconds < base_seconds:
            raise ValueError("Require 1 <= base_seconds <= max_seconds")
        self._base_seconds = base_seconds
        self._max_seconds = max_seconds
        self._jitter = jitter
        self._rng = rng or random.Random()

    @property
    def base_seconds(self) -> int:
        return self._base_seconds

    @property
    def max_seconds(self) -> int:
        return self._max_seconds

    def delay_for(self, retry_number: int) -> int:
        """Seconds to wait before retry number `retry_number` (0 = first retry)."""
        exponent = min(max(retry_number, 0), self._MAX_EXPONENT)
        ceiling = min(self._max_seconds, self._base_seconds * (2**exponent))
        if not self._jitter:
            return ceiling
        return self._rng.randint(max(1, ceiling // 2), ceiling)


retry_policy = RetryPolicy(settings.RETRY_BASE_SECONDS, settings.RETRY_MAX_SECONDS)
