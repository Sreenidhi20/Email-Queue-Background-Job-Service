import unittest

from src.core.errors import TooManyRequestsError
from src.infrastructure.rate_limiter import (
    CounterStoreUnavailable,
    RateLimitGuard,
    RateLimiter,
)


class FakeCounterStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.down = False

    def increment_window(self, key: str, ttl_seconds: int) -> int:
        if self.down:
            raise CounterStoreUnavailable("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        self.ttls[key] = ttl_seconds
        return self.counts[key]


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RateLimiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeCounterStore()
        self.clock = Clock(1_000_020.0)       # 20 seconds into a window
        self.limiter = RateLimiter(self.store, limit=3, clock=self.clock)

    def test_allows_up_to_the_limit_then_blocks_with_retry_after(self) -> None:
        results = [self.limiter.check("app", "emails") for _ in range(4)]

        self.assertEqual([r.allowed for r in results], [True, True, True, False])
        self.assertEqual([r.remaining for r in results], [2, 1, 0, 0])
        self.assertTrue(1 <= results[3].retry_after_seconds <= 61)

    def test_each_client_has_its_own_counter(self) -> None:
        for _ in range(3):
            self.limiter.check("app-a", "emails")

        self.assertFalse(self.limiter.check("app-a", "emails").allowed)
        self.assertTrue(self.limiter.check("app-b", "emails").allowed)

    def test_counter_resets_in_the_next_window(self) -> None:
        for _ in range(4):
            self.limiter.check("app", "emails")
        self.clock.now += 60

        self.assertTrue(self.limiter.check("app", "emails").allowed)

    def test_counter_keys_expire_by_themselves(self) -> None:
        self.limiter.check("app", "emails")

        self.assertEqual(list(self.store.ttls.values()), [61])

    def test_fails_open_when_the_store_is_down(self) -> None:
        self.store.down = True

        self.assertTrue(self.limiter.check("app", "emails").allowed)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            RateLimiter(self.store, limit=0)


class RateLimitGuardTests(unittest.TestCase):
    def test_guard_raises_429_with_retry_after_once_over_limit(self) -> None:
        limiter = RateLimiter(FakeCounterStore(), limit=2, clock=Clock(1_000_000.0))
        guard = RateLimitGuard(limiter, "emails")
        guard("app")
        guard("app")

        with self.assertRaises(TooManyRequestsError) as raised:
            guard("app")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("2 requests per minute", raised.exception.detail)
        self.assertGreaterEqual(raised.exception.retry_after_seconds, 1)


if __name__ == "__main__":
    unittest.main()
