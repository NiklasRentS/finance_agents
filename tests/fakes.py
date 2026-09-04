"""In-memory provider implementations used to test agents without network access."""

from __future__ import annotations

from datetime import date

from app.domain.company import Company, Listing
from app.domain.facts import Confidence, Fact, FactKind, Period, PeriodType, SourceRef, SourceTier
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric, NumericFact
from app.ports.exceptions import CompanyNotFoundError, ProviderUnavailableError
from app.ports.fundamentals import FundamentalsProvider
from app.ports.market_data import MarketDataProvider, PricePoint, Quote

FAKE_SOURCE = SourceRef(provider="fake", tier=SourceTier.REGULATORY_FILING)
FAKE_FILING = SourceRef(
    provider="SEC EDGAR",
    tier=SourceTier.REGULATORY_FILING,
    title="Form 10-K",
    url="https://www.sec.gov/example",
    document_id="0000320193-25-000079",
)
FAKE_MARKET_SOURCE = SourceRef(
    provider="Yahoo Finance", tier=SourceTier.FINANCIAL_DATA_PROVIDER, url="https://example.com"
)

COMPLETE_FIGURES: dict[Metric, float] = {
    Metric.REVENUE: 400_000.0,
    Metric.COST_OF_REVENUE: 210_000.0,
    Metric.OPERATING_INCOME: 125_000.0,
    Metric.DEPRECIATION_AMORTIZATION: 12_000.0,
    Metric.PRETAX_INCOME: 125_000.0,
    Metric.INCOME_TAX_EXPENSE: 25_000.0,
    Metric.NET_INCOME: 100_000.0,
    Metric.EPS_DILUTED: 6.5,
    Metric.OPERATING_CASH_FLOW: 118_000.0,
    Metric.CAPITAL_EXPENDITURE: 12_000.0,
    Metric.CASH_AND_EQUIVALENTS: 30_000.0,
    Metric.SHORT_TERM_INVESTMENTS: 20_000.0,
    Metric.SHORT_TERM_DEBT: 10_000.0,
    Metric.LONG_TERM_DEBT: 90_000.0,
    Metric.TOTAL_ASSETS: 350_000.0,
    Metric.TOTAL_CURRENT_ASSETS: 150_000.0,
    Metric.TOTAL_CURRENT_LIABILITIES: 140_000.0,
    Metric.TOTAL_EQUITY: 70_000.0,
    Metric.SHARES_OUTSTANDING: 15_000.0,
    Metric.SHARES_DILUTED: 15_100.0,
}


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


class CompleteFakeFundamentals(FundamentalsProvider):
    """Full income statement, balance sheet and cash flow, for end-to-end tests."""

    name = "complete_fake"

    def __init__(
        self,
        *,
        years: tuple[int, ...] = (2023, 2024, 2025),
        omit: set[Metric] | None = None,
    ) -> None:
        self._years = years
        self._omit = omit or set()

    def close(self) -> None:
        return None

    def resolve_company(self, identifier: str) -> Company:
        return Company(
            name="Example Corp.",
            cik="320193",
            listings=[Listing(ticker="EXMP", exchange="NASDAQ", currency="USD")],
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
        for index, year in enumerate(self._years):
            period = Period.fiscal_year_of(year, end=date(year, 9, 30))
            growth = 1.0 + 0.08 * index
            snapshots.append(
                FinancialSnapshot(
                    period=period,
                    values={
                        metric: _reported(value * growth, period)
                        for metric, value in COMPLETE_FIGURES.items()
                        if metric not in self._omit
                    },
                )
            )
        return FinancialHistory(currency="USD", snapshots=snapshots[-max_periods:])


class ConfigurableFakeMarketData(MarketDataProvider):
    name = "configurable_fake_market"

    def __init__(self, *, fail: bool = False, price: float = 250.0) -> None:
        self._fail = fail
        self._price = price

    def close(self) -> None:
        return None

    def get_quote(self, ticker: str) -> Quote:
        if self._fail:
            raise ProviderUnavailableError(self.name, "upstream down")
        return Quote(
            ticker=ticker,
            price=Fact[float](
                value=self._price,
                unit="USD",
                kind=FactKind.REPORTED,
                confidence=Confidence.HIGH,
                sources=[FAKE_MARKET_SOURCE],
            ),
            currency="USD",
            as_of=date(2025, 12, 1),
        )

    def get_historical_prices(
        self, ticker: str, *, start: date, end: date | None = None
    ) -> list[PricePoint]:
        return [PricePoint(date=start, close=self._price)]


def _reported(value: float, period: Period) -> NumericFact:
    return Fact[float](
        value=value,
        unit="USD",
        period=period,
        kind=FactKind.REPORTED,
        confidence=Confidence.HIGH,
        sources=[FAKE_FILING],
    )
