"""Live checks against Yahoo Finance. Run with: pytest -m integration"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest

from app.domain.facts import FactKind
from app.providers.yahoo.provider import YahooFinanceMarketDataProvider

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def provider() -> Iterator[YahooFinanceMarketDataProvider]:
    adapter = YahooFinanceMarketDataProvider.build()
    yield adapter
    adapter.close()


def test_quote_for_apple_is_plausible(provider: YahooFinanceMarketDataProvider) -> None:
    quote = provider.get_quote("AAPL")
    assert quote.price.value is not None
    assert 1.0 < quote.price.value < 10_000.0, "sanity band, not a valuation claim"
    assert quote.price.kind is FactKind.REPORTED
    assert quote.currency == "USD"
    assert quote.price.sources[0].url


def test_history_covers_the_requested_window(provider: YahooFinanceMarketDataProvider) -> None:
    end = date.today()
    points = provider.get_historical_prices("AAPL", start=end - timedelta(days=60), end=end)
    assert len(points) > 20, "roughly one trading day per business day"
    assert points == sorted(points, key=lambda point: point.date)
    assert all(point.close > 0 for point in points)
