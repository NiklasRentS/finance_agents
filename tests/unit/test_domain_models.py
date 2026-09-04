"""Tests for company identity and financial history containers."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.company import Company, Listing
from app.domain.facts import NOT_AVAILABLE, Fact, FactKind, Period, SourceRef, SourceTier
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric

SEC_SOURCE = SourceRef(provider="SEC EDGAR", tier=SourceTier.REGULATORY_FILING)


def _snapshot(year: int, revenue: float | None) -> FinancialSnapshot:
    period = Period.fiscal_year_of(year, end=date(year, 9, 30))
    values = {}
    if revenue is not None:
        values[Metric.REVENUE] = Fact[float](
            value=revenue,
            unit="USDm",
            period=period,
            kind=FactKind.REPORTED,
            sources=[SEC_SOURCE],
        )
    return FinancialSnapshot(period=period, values=values)


class TestCompany:
    def test_cik_is_zero_padded(self) -> None:
        company = Company(name="Apple Inc.", cik="320193")
        assert company.cik == "0000320193"

    def test_non_numeric_cik_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="numeric"):
            Company(name="Apple Inc.", cik="ABC123")

    def test_ticker_is_normalised(self) -> None:
        listing = Listing(ticker="  aapl ")
        assert listing.ticker == "AAPL"

    def test_empty_ticker_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Listing(ticker="   ")

    def test_primary_ticker_prefers_primary_listing(self) -> None:
        company = Company(
            name="Apple Inc.",
            listings=[
                Listing(ticker="APC", exchange="XETRA", is_primary=False),
                Listing(ticker="AAPL", exchange="NASDAQ", is_primary=True),
            ],
        )
        assert company.primary_ticker == "AAPL"

    def test_primary_ticker_is_none_without_listings(self) -> None:
        assert Company(name="Private Co").primary_ticker is None


class TestFinancialHistory:
    def test_series_is_chronological(self) -> None:
        history = FinancialHistory(
            currency="USD",
            snapshots=[_snapshot(2024, 391_035.0), _snapshot(2022, 394_328.0)],
        )
        labels = [period.label for period, _ in history.series(Metric.REVENUE)]
        assert labels == ["FY2022", "FY2024"]

    def test_missing_metric_yields_explicit_na(self) -> None:
        history = FinancialHistory(snapshots=[_snapshot(2024, 391_035.0)])
        fact = history.snapshots[0].get(Metric.EBITDA)
        assert not fact.is_available
        assert fact.display() == NOT_AVAILABLE

    def test_available_series_skips_missing_periods(self) -> None:
        history = FinancialHistory(
            snapshots=[
                _snapshot(2022, 394_328.0),
                _snapshot(2023, None),
                _snapshot(2024, 391_035.0),
            ]
        )
        available = history.available_series(Metric.REVENUE)
        assert [p.label for p, _ in available] == ["FY2022", "FY2024"]
        assert [v for _, v in available] == [394_328.0, 391_035.0]

    def test_latest_returns_most_recent_available_value(self) -> None:
        history = FinancialHistory(snapshots=[_snapshot(2023, 383_285.0), _snapshot(2024, None)])
        latest = history.latest(Metric.REVENUE)
        assert latest is not None
        assert latest.value == pytest.approx(383_285.0)

    def test_latest_is_none_when_metric_never_reported(self) -> None:
        history = FinancialHistory(snapshots=[_snapshot(2024, 391_035.0)])
        assert history.latest(Metric.ROIC) is None
