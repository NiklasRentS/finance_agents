"""HTTP client shared by every provider adapter.

Bundles the four cross-cutting concerns that would otherwise be reimplemented
in each adapter: timeouts, retries, rate limiting and caching.
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import TracebackType
from typing import Any, Self

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.infra.cache import DiskCache, cache_key
from app.infra.cost import CostTracker
from app.infra.logging import get_logger
from app.infra.rate_limit import RateLimiter

logger = get_logger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class HttpError(RuntimeError):
    """Non-retryable HTTP failure."""

    def __init__(self, message: str, *, status_code: int | None = None, url: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class RetryableHttpError(HttpError):
    """Transient failure worth retrying."""


class HttpClient:
    """Synchronous HTTP client with caching, retry and budget enforcement."""

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limiter: RateLimiter | None = None,
        cache: DiskCache | None = None,
        cost_tracker: CostTracker | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.provider_name = provider_name
        self._max_retries = max_retries
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._cost_tracker = cost_tracker
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            headers=headers or {},
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        ttl: timedelta | None = None,
        operation: str = "get",
        cost_usd: float = 0.0,
    ) -> str:
        """GET a URL as text. ``ttl=None`` bypasses the cache."""
        key = cache_key(self.provider_name, url, json.dumps(params or {}, sort_keys=True))

        if self._cache is not None and ttl is not None:
            cached = self._cache.get(key)
            if cached is not None:
                if self._cost_tracker is not None:
                    self._cost_tracker.record_request(self.provider_name, operation, cached=True)
                logger.debug("http.cache_hit", provider=self.provider_name, url=url)
                return cached

        if self._cost_tracker is not None:
            self._cost_tracker.record_request(self.provider_name, operation, cost_usd=cost_usd)

        body = self._fetch_with_retry(url, params)

        if self._cache is not None and ttl is not None:
            self._cache.set(key, body, ttl)
        return body

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        ttl: timedelta | None = None,
        operation: str = "get",
        cost_usd: float = 0.0,
    ) -> Any:
        raw = self.get_text(url, params=params, ttl=ttl, operation=operation, cost_usd=cost_usd)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HttpError(f"Response from {url} was not valid JSON: {exc}", url=url) from exc

    def _fetch_with_retry(self, url: str, params: dict[str, str | int] | None) -> str:
        retrying = Retrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=retry_if_exception_type(RetryableHttpError),
            before_sleep=self._log_retry,
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                return self._fetch_once(url, params)
        raise HttpError(f"Request to {url} failed without a result", url=url)

    def _fetch_once(self, url: str, params: dict[str, str | int] | None) -> str:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise RetryableHttpError(f"Timeout requesting {url}", url=url) from exc
        except httpx.TransportError as exc:
            raise RetryableHttpError(f"Transport error requesting {url}: {exc}", url=url) from exc

        if response.status_code in RETRYABLE_STATUS:
            raise RetryableHttpError(
                f"Transient HTTP {response.status_code} from {url}",
                status_code=response.status_code,
                url=url,
            )
        if response.status_code >= 400:
            raise HttpError(
                f"HTTP {response.status_code} from {url}",
                status_code=response.status_code,
                url=url,
            )
        return response.text

    def _log_retry(self, state: RetryCallState) -> None:
        logger.warning(
            "http.retry",
            provider=self.provider_name,
            attempt=state.attempt_number,
            error=str(state.outcome.exception()) if state.outcome else None,
        )
