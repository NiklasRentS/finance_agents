"""Tests for the client-side rate limiter."""

from __future__ import annotations

import pytest

from app.infra.rate_limit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TestRateLimiter:
    def test_rejects_non_positive_rate(self) -> None:
        with pytest.raises(ValueError, match="greater than zero"):
            RateLimiter(0)

    def test_first_acquire_does_not_wait(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(8, monotonic=clock.monotonic, sleep=clock.sleep)
        assert limiter.acquire() == 0.0
        assert clock.sleeps == []

    def test_second_acquire_waits_min_interval(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(8, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        waited = limiter.acquire()
        assert waited == pytest.approx(0.125)
        assert clock.sleeps == [pytest.approx(0.125)]

    def test_no_wait_when_enough_time_has_passed(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(8, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        clock.now = 10.0
        assert limiter.acquire() == 0.0

    def test_sustained_rate_matches_configuration(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(8, monotonic=clock.monotonic, sleep=clock.sleep)
        for _ in range(8):
            limiter.acquire()
        assert clock.now == pytest.approx(0.875)
