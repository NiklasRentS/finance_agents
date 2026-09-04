"""Tests for the Yahoo Finance market data adapter."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from app.domain.facts import FactKind, SourceTier
from app.infra.http import HttpClient
from app.ports.exceptions import (
    CompanyNotFoundError,
    DataNotAvailableError,
    ProviderUnavailableError,
)
from app.providers.yahoo.provider import YahooFinanceMarketDataProvider

# 2025-01-02, 2025-01-03, 2025-01-06 at 14:30 UTC (market open in New York).
TIMESTAMPS = [1735828200, 1735914600, 1736173800]
GMT_OFFSET = -18000  # EST


def _payload(
    *,
    closes: list[float | None] | None = None,
    volumes: list[float | None] | None = None,
    price: float | None = 245.0,
) -> dict[str, object]:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "symbol": "AAPL",
                        "fullExchangeName": "NasdaqGS",
                        "regularMarketPrice": price,
                        "regularMarketTime": TIMESTAMPS[-1],
                        "gmtoffset": GMT_OFFSET,
                    },
                    "timestamp": TIMESTAMPS,
                    "indicators": {
                        "quote": [
                            {
                                "close": closes if closes is not None else [243.85, 243.36, 245.0],
                                "volume": volumes
                                if volumes is not None
                                else [55740700, 40244100, 45045600],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _provider() -> YahooFinanceMarketDataProvider:
    return YahooFinanceMarketDataProvider(HttpClient(provider_name="yahoo", max_retries=0))


def _route() -> respx.Route:
    return respx.route(method="GET", host="query1.finance.yahoo.com")


class TestQuote:
    @respx.mock
    def test_latest_price_is_returned(self) -> None:
        _route().mock(return_value=httpx.Response(200, json=_payload()))
        quote = _provider().get_quote("aapl")
        assert quote.ticker == "AAPL"
        assert quote.price.value == pytest.approx(245.0)
        assert quote.currency == "USD"
        assert quote.as_of == date(2025, 1, 6)

    @respx.mock
    def test_price_is_reported_and_sourced(self) -> None:
        _route().mock(return_value=httpx.Response(200, json=_payload()))
        price = _provider().get_quote("AAPL").price
        assert price.kind is FactKind.REPORTED
        assert price.unit == "USD"
        source = price.sources[0]
        assert source.provider == "Yahoo Finance"
        assert source.tier is SourceTier.FINANCIAL_DATA_PROVIDER
        assert source.url == "https://finance.yahoo.com/quote/AAPL/history"

    @respx.mock
    def test_missing_price_yields_data_not_available(self) -> None:
        _route().mock(return_value=httpx.Response(200, json=_payload(price=None)))
        with pytest.raises(DataNotAvailableError):
            _provider().get_quote("AAPL")

    @respx.mock
    def test_unknown_ticker_raises_company_not_found(self) -> None:
        body = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data"}}}
        _route().mock(return_value=httpx.Response(404, json=body))
        with pytest.raises(CompanyNotFoundError):
            _provider().get_quote("NOSUCHTICKER")

    @respx.mock
    def test_error_field_without_404_is_still_detected(self) -> None:
        body = {"chart": {"result": None, "error": {"description": "No data found"}}}
        _route().mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(CompanyNotFoundError, match="No data found"):
            _provider().get_quote("NOSUCHTICKER")

    @respx.mock
    def test_upstream_failure_becomes_provider_error(self) -> None:
        _route().mock(return_value=httpx.Response(503))
        with pytest.raises(ProviderUnavailableError):
            _provider().get_quote("AAPL")

    def test_empty_ticker_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            _provider().get_quote("   ")


class TestHistoricalPrices:
    @respx.mock
    def test_points_are_chronological_local_dates(self) -> None:
        _route().mock(return_value=httpx.Response(200, json=_payload()))
        points = _provider().get_historical_prices("AAPL", start=date(2025, 1, 1))
        assert [point.date for point in points] == [
            date(2025, 1, 2),
            date(2025, 1, 3),
            date(2025, 1, 6),
        ]
        assert points[0].close == pytest.approx(243.85)
        assert points[0].volume == pytest.approx(55740700)

    @respx.mock
    def test_null_closes_are_skipped(self) -> None:
        _route().mock(return_value=httpx.Response(200, json=_payload(closes=[243.85, None, 245.0])))
        points = _provider().get_historical_prices("AAPL", start=date(2025, 1, 1))
        assert [point.date for point in points] == [date(2025, 1, 2), date(2025, 1, 6)]

    @respx.mock
    def test_requested_window_is_passed_upstream(self) -> None:
        route = _route().mock(return_value=httpx.Response(200, json=_payload()))
        _provider().get_historical_prices("AAPL", start=date(2024, 1, 1), end=date(2024, 12, 31))
        url = route.calls[0].request.url
        assert url.path == "/v8/finance/chart/AAPL"
        assert url.params["period1"] == "1704067200"
        assert url.params["interval"] == "1d"

    @respx.mock
    def test_response_without_timestamps_is_empty(self) -> None:
        body: dict[str, object] = {
            "chart": {"result": [{"meta": {}, "indicators": {}}], "error": None}
        }
        _route().mock(return_value=httpx.Response(200, json=body))
        assert _provider().get_historical_prices("AAPL", start=date(2025, 1, 1)) == []
