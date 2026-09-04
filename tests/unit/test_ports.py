"""Contract tests for the provider ports."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.financials import Metric
from app.ports.exceptions import CompanyNotFoundError
from app.ports.fundamentals import FundamentalsProvider
from app.ports.market_data import MarketDataProvider
from tests.fakes import FakeFundamentalsProvider, FakeMarketDataProvider


class TestPortsAreAbstract:
    def test_incomplete_market_data_provider_cannot_be_instantiated(self) -> None:
        class Incomplete(MarketDataProvider):
            name = "incomplete"

            def get_quote(self, ticker: str) -> None:  # type: ignore[override]
                return None

        with pytest.raises(TypeError, match="abstract"):
            Incomplete()  # type: ignore[abstract]

    def test_incomplete_fundamentals_provider_cannot_be_instantiated(self) -> None:
        class Incomplete(FundamentalsProvider):
            name = "incomplete"

        with pytest.raises(TypeError, match="abstract"):
            Incomplete()  # type: ignore[abstract]


class TestFakeProvidersSatisfyTheContract:
    def test_market_data_fake_is_a_provider(self) -> None:
        provider = FakeMarketDataProvider(price=250.0)
        assert isinstance(provider, MarketDataProvider)
        quote = provider.get_quote("AAPL")
        assert quote.price.value == pytest.approx(250.0)
        assert quote.price.sources, "quotes must carry a source"

    def test_historical_prices_are_returned(self) -> None:
        provider = FakeMarketDataProvider()
        points = provider.get_historical_prices("AAPL", start=date(2024, 1, 1))
        assert points and points[0].date == date(2024, 1, 1)

    def test_fundamentals_fake_resolves_company(self) -> None:
        provider = FakeFundamentalsProvider()
        company = provider.resolve_company("aapl")
        assert company.cik == "0000320193"
        assert company.primary_ticker == "AAPL"

    def test_unknown_identifier_raises_domain_error(self) -> None:
        with pytest.raises(CompanyNotFoundError, match="unknown identifier"):
            FakeFundamentalsProvider().resolve_company("NOPE")

    def test_history_respects_max_periods(self) -> None:
        provider = FakeFundamentalsProvider()
        company = provider.resolve_company("AAPL")
        history = provider.get_financial_history(company, max_periods=2)
        labels = [p.label for p, _ in history.series(Metric.REVENUE)]
        assert labels == ["FY2023", "FY2024"]
