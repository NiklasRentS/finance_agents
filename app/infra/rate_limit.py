"""Client-side rate limiting.

The SEC publishes an explicit access limit; exceeding it gets the client
blocked, so the limiter is a correctness concern rather than politeness.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock


class RateLimiter:
    """Blocking limiter enforcing a minimum interval between acquisitions."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than zero")
        self._min_interval = 1.0 / requests_per_second
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = Lock()
        self._next_allowed_at: float | None = None

    @property
    def min_interval(self) -> float:
        return self._min_interval

    def acquire(self) -> float:
        """Block until the next request is permitted. Returns seconds waited."""
        with self._lock:
            now = self._monotonic()
            if self._next_allowed_at is None or now >= self._next_allowed_at:
                self._next_allowed_at = now + self._min_interval
                return 0.0
            wait_for = self._next_allowed_at - now
            self._next_allowed_at += self._min_interval

        self._sleep(wait_for)
        return wait_for
