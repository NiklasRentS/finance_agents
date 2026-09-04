"""In-memory provider implementations used to test agents without network access."""

from __future__ import annotations

from datetime import date

from app.domain.company import Company, Listing
from app.domain.facts import Confidence, Fact, FactKind, Period, PeriodType, SourceRef, SourceTier
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric
from app.ports.exceptions import CompanyNotFoundError
from app.ports.fundamentals import FundamentalsProvider
from app.ports.market_data import MarketDataProvider, PricePoint, Quote

FAKE_SOURCE = SourceRef(provider="fake", tier=SourceTier.REGULATORY_FILING)


class FakeMarketDataProvider(MarketDataProvider):
    name = "fake_market_data"

    def __init__(self, price: float = 100.0) -> None:
        self._price = price

    def get_quote(self, ticker: str) -> Quote:
        return Quote(
            ticker=ticker,
            price=Fact[float](
                value=self._price,
                unit="USD",
                kind=FactKind.REPORTED,
                confidence=Confidence.HIGH,
                sources=[FAKE_SOURCE],
            ),
            currency="USD",
            as_of=date(2025, 1, 2),
        )

    def get_historical_prices(
        self, ticker: str, *, start: date, end: date | None = None
    ) -> list[PricePoint]:
        return [PricePoint(date=start, close=self._price)]


class FakeFundamentalsProvider(FundamentalsProvider):
    name = "fake_fundamentals"

    def __init__(self, revenues: dict[int, float] | None = None) -> None:
        self._revenues = revenues or {2022: 100.0, 2023: 120.0, 2024: 150.0}

    def resolve_company(self, identifier: str) -> Company:
        if identifier.upper() != "AAPL":
            raise CompanyNotFoundError(self.name, f"unknown identifier {identifier!r}")
        return Company(
            name="Apple Inc.",
            cik="320193",
            listings=[Listing(ticker="AAPL", exchange="NASDAQ", currency="USD")],
            reporting_currency="USD",
        )

    def get_financial_history(
        self,
        company: Company,
        *,
        period_type: PeriodType = PeriodType.FISCAL_YEAR,
        max_periods: int = 10,
    ) -> FinancialHistory:
        snapshots = []
        for year, revenue in sorted(self._revenues.items()):
            period = Period.fiscal_year_of(year, end=date(year, 9, 30))
            snapshots.append(
                FinancialSnapshot(
                    period=period,
                    values={
                        Metric.REVENUE: Fact[float](
                            value=revenue,
                            unit="USDm",
                            period=period,
                            kind=FactKind.REPORTED,
                            confidence=Confidence.HIGH,
                            sources=[FAKE_SOURCE],
                        )
                    },
                )
            )
        return FinancialHistory(currency="USD", snapshots=snapshots[-max_periods:])
