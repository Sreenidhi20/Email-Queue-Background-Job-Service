import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import redis
from fastapi import Depends

from src.core.config import settings
from src.core.errors import TooManyRequestsError
from src.core.security import api_key_auth
from src.infrastructure.redis import RedisClient, redis_client


class CounterStoreUnavailable(Exception):
    """The counter store (Redis) could not be reached."""


class CounterStore(Protocol):
    def increment_window(self, key: str, ttl_seconds: int) -> int: ...


class RedisCounterStore:
    """Counts hits per key in Redis; the key expires on its own."""

    def __init__(self, client: RedisClient) -> None:
        self._client = client

    def increment_window(self, key: str, ttl_seconds: int) -> int:
        try:
            pipe = self._client.client.pipeline(transaction=True)  # type: ignore[reportUnknownMemberType]
            pipe.set(key, 0, ex=ttl_seconds, nx=True)  # create with expiry only if new
            pipe.incr(key)
            results = pipe.execute()  # type: ignore[reportUnknownMemberType]
        except redis.RedisError as error:
            raise CounterStoreUnavailable(str(error)) from error
        return int(results[1])


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    """Fixed-window limiter: at most `limit` calls per client per window.

    Trade-off: a client can burst up to 2x the limit across a window boundary.
    If Redis is down the limiter allows the request (the queue itself would
    then fail with 503 anyway), rather than blocking every caller.
    """

    def __init__(
        self,
        store: CounterStore,
        limit: int,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be at least 1")
        self._store = store
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock

    @property
    def limit(self) -> int:
        return self._limit

    def check(self, client: str, scope: str) -> RateLimitDecision:
        now = self._clock()
        window_index = int(now // self._window_seconds)
        retry_after = max(1, int((window_index + 1) * self._window_seconds - now) + 1)
        key = f"ratelimit:{scope}:{client}:{window_index}"
        try:
            count = self._store.increment_window(key, self._window_seconds + 1)
        except CounterStoreUnavailable:
            return RateLimitDecision(True, self._limit, 0)
        remaining = max(0, self._limit - count)
        return RateLimitDecision(count <= self._limit, remaining, retry_after)


class RateLimitGuard:
    """FastAPI dependency: raises 429 when the calling client is over its limit."""

    def __init__(self, limiter: RateLimiter, scope: str) -> None:
        self._limiter = limiter
        self._scope = scope

    def __call__(self, client: str = Depends(api_key_auth)) -> None:
        decision = self._limiter.check(client, self._scope)
        if not decision.allowed:
            raise TooManyRequestsError(
                decision.retry_after_seconds,
                f"Limit is {self._limiter.limit} requests per minute per API key",
            )


rate_limiter = RateLimiter(RedisCounterStore(redis_client), settings.RATE_LIMIT_PER_MINUTE)
create_email_rate_limit = RateLimitGuard(rate_limiter, scope="emails.create")
