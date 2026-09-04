"""Tests for the shared HTTP client: retries, caching and budget enforcement."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx

from app.infra.cache import DiskCache
from app.infra.cost import BudgetExceededError, CostTracker
from app.infra.http import HttpClient, HttpError

URL = "https://data.sec.gov/api/companyfacts.json"


def _client(**kwargs: object) -> HttpClient:
    defaults: dict[str, object] = {"provider_name": "sec_edgar", "max_retries": 2}
    defaults.update(kwargs)
    return HttpClient(**defaults)  # type: ignore[arg-type]


class TestRequests:
    @respx.mock
    def test_get_json_parses_payload(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json={"cik": 320193}))
        with _client() as client:
            assert client.get_json(URL) == {"cik": 320193}

    @respx.mock
    def test_invalid_json_raises(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, text="<html>"))
        with _client() as client, pytest.raises(HttpError, match="not valid JSON"):
            client.get_json(URL)

    @respx.mock
    def test_client_error_is_not_retried(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(404))
        with _client() as client, pytest.raises(HttpError) as exc:
            client.get_json(URL)
        assert exc.value.status_code == 404
        assert route.call_count == 1

    @respx.mock
    def test_transient_error_is_retried(self) -> None:
        route = respx.get(URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        with _client() as client:
            assert client.get_json(URL) == {"ok": True}
        assert route.call_count == 2

    @respx.mock
    def test_retries_are_bounded(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(503))
        with _client(max_retries=1) as client, pytest.raises(HttpError, match="Transient"):
            client.get_json(URL)
        assert route.call_count == 2


class TestCaching:
    @respx.mock
    def test_second_call_is_served_from_cache(self, tmp_path: Path) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"v": 1}))
        cache = DiskCache(tmp_path)
        with _client(cache=cache) as client:
            first = client.get_json(URL, ttl=timedelta(hours=1))
            second = client.get_json(URL, ttl=timedelta(hours=1))
        assert first == second == {"v": 1}
        assert route.call_count == 1

    @respx.mock
    def test_without_ttl_nothing_is_cached(self, tmp_path: Path) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"v": 1}))
        with _client(cache=DiskCache(tmp_path)) as client:
            client.get_json(URL)
            client.get_json(URL)
        assert route.call_count == 2

    @respx.mock
    def test_differing_params_use_separate_entries(self, tmp_path: Path) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"v": 1}))
        with _client(cache=DiskCache(tmp_path)) as client:
            client.get_json(URL, params={"cik": 1}, ttl=timedelta(hours=1))
            client.get_json(URL, params={"cik": 2}, ttl=timedelta(hours=1))
        assert route.call_count == 2


class TestBudgetIntegration:
    @respx.mock
    def test_requests_are_recorded(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        tracker = CostTracker(max_cost_usd=0.0, max_requests=5)
        with _client(cost_tracker=tracker) as client:
            client.get_json(URL)
        assert tracker.external_requests == 1

    @respx.mock
    def test_exceeded_budget_prevents_the_network_call(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        tracker = CostTracker(max_cost_usd=0.0, max_requests=0)
        with _client(cost_tracker=tracker) as client, pytest.raises(BudgetExceededError):
            client.get_json(URL)
        assert route.call_count == 0

    @respx.mock
    def test_cache_hits_are_recorded_separately(self, tmp_path: Path) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        tracker = CostTracker(max_cost_usd=0.0, max_requests=1)
        with _client(cache=DiskCache(tmp_path), cost_tracker=tracker) as client:
            client.get_json(URL, ttl=timedelta(hours=1))
            client.get_json(URL, ttl=timedelta(hours=1))
        assert tracker.external_requests == 1
        assert tracker.cache_hits == 1
