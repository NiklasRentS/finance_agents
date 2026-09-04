"""Tests for the SEC EDGAR adapter."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
import respx

from app.domain.company import Company
from app.domain.facts import FactKind, PeriodType
from app.domain.financials import Metric
from app.infra.http import HttpClient
from app.ports.exceptions import CompanyNotFoundError, ProviderUnavailableError
from app.providers.sec_edgar.provider import (
    COMPANYFACTS_URL,
    SUBMISSIONS_URL,
    TICKERS_URL,
    SecEdgarFundamentalsProvider,
    fiscal_year_for,
)

CIK = "0000320193"
ACCN_2024 = "0000320193-24-000123"
ACCN_2023 = "0000320193-23-000106"

APPLE = Company(name="Apple Inc.", cik=CIK)


def _provider() -> SecEdgarFundamentalsProvider:
    return SecEdgarFundamentalsProvider(HttpClient(provider_name="sec_edgar", max_retries=0))


def _companyfacts(us_gaap: dict[str, Any]) -> dict[str, Any]:
    return {"cik": 320193, "entityName": "Apple Inc.", "facts": {"us-gaap": us_gaap}}


REVENUE_TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"

REVENUE_ROWS = {
    "units": {
        "USD": [
            {
                "start": "2022-09-25",
                "end": "2023-09-30",
                "val": 383285000000,
                "accn": ACCN_2023,
                "form": "10-K",
                "filed": "2023-11-03",
            },
            {
                "start": "2023-10-01",
                "end": "2024-09-28",
                "val": 391035000000,
                "accn": ACCN_2024,
                "form": "10-K",
                "filed": "2024-11-01",
            },
            {
                "start": "2024-06-30",
                "end": "2024-09-28",
                "val": 94930000000,
                "accn": ACCN_2024,
                "form": "10-K",
                "filed": "2024-11-01",
            },
            {
                "start": "2024-03-31",
                "end": "2024-06-29",
                "val": 85777000000,
                "accn": "0000320193-24-000081",
                "form": "10-Q",
                "filed": "2024-08-02",
            },
        ]
    }
}

ASSETS_ROWS = {
    "units": {
        "USD": [
            {
                "end": "2024-09-28",
                "val": 364980000000,
                "accn": ACCN_2024,
                "form": "10-K",
                "filed": "2024-11-01",
            },
            {
                "end": "2023-09-30",
                "val": 352583000000,
                "accn": ACCN_2023,
                "form": "10-K",
                "filed": "2023-11-03",
            },
        ]
    }
}


class TestFiscalYearNormalisation:
    def test_late_year_end_keeps_its_year(self) -> None:
        assert fiscal_year_for(date(2024, 9, 28)) == 2024

    def test_december_year_end_keeps_its_year(self) -> None:
        assert fiscal_year_for(date(2024, 12, 31)) == 2024

    def test_early_year_end_belongs_to_previous_year(self) -> None:
        assert fiscal_year_for(date(2025, 1, 31)) == 2024


class TestResolveCompany:
    @respx.mock
    def test_ticker_is_resolved_to_cik(self) -> None:
        respx.get(TICKERS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"},
                },
            )
        )
        respx.get(SUBMISSIONS_URL.format(cik=CIK)).mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "Apple Inc.",
                    "tickers": ["AAPL"],
                    "exchanges": ["Nasdaq"],
                    "sicDescription": "Electronic Computers",
                    "fiscalYearEnd": "0928",
                    "addresses": {"business": {"stateOrCountry": "CA"}},
                },
            )
        )
        company = _provider().resolve_company("aapl")
        assert company.cik == CIK
        assert company.primary_ticker == "AAPL"
        assert company.fiscal_year_end_month == 9
        assert company.industry == "Electronic Computers"

    @respx.mock
    def test_unknown_ticker_raises(self) -> None:
        respx.get(TICKERS_URL).mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(CompanyNotFoundError, match="No SEC filer"):
            _provider().resolve_company("NOSUCH")

    @respx.mock
    def test_numeric_identifier_skips_the_ticker_lookup(self) -> None:
        route = respx.get(TICKERS_URL).mock(return_value=httpx.Response(200, json={}))
        respx.get(SUBMISSIONS_URL.format(cik=CIK)).mock(
            return_value=httpx.Response(200, json={"name": "Apple Inc."})
        )
        assert _provider().resolve_company("320193").cik == CIK
        assert route.call_count == 0

    @respx.mock
    def test_missing_filer_becomes_domain_error(self) -> None:
        respx.get(SUBMISSIONS_URL.format(cik="0000000001")).mock(return_value=httpx.Response(404))
        with pytest.raises(CompanyNotFoundError, match="no data"):
            _provider().resolve_company("1")

    @respx.mock
    def test_server_error_becomes_provider_error(self) -> None:
        respx.get(SUBMISSIONS_URL.format(cik="0000000001")).mock(return_value=httpx.Response(403))
        with pytest.raises(ProviderUnavailableError):
            _provider().resolve_company("1")


class TestFinancialHistory:
    @respx.mock
    def _history(self, us_gaap: dict[str, Any], **kwargs: Any) -> Any:
        respx.get(COMPANYFACTS_URL.format(cik=CIK)).mock(
            return_value=httpx.Response(200, json=_companyfacts(us_gaap))
        )
        return _provider().get_financial_history(APPLE, **kwargs)

    def test_annual_values_are_extracted(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS, "Assets": ASSETS_ROWS})
        series = history.available_series(Metric.REVENUE)
        assert [p.label for p, _ in series] == ["FY2023", "FY2024"]
        assert [v for _, v in series] == [383285000000.0, 391035000000.0]

    def test_quarterly_rows_are_ignored(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS})
        values = [v for _, v in history.available_series(Metric.REVENUE)]
        assert 94930000000.0 not in values, "Q4 figure inside the 10-K must be excluded"
        assert 85777000000.0 not in values, "10-Q figure must be excluded"

    def test_instant_metrics_are_extracted(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS, "Assets": ASSETS_ROWS})
        assets = history.available_series(Metric.TOTAL_ASSETS)
        assert [v for _, v in assets] == [352583000000.0, 364980000000.0]

    def test_restated_value_supersedes_the_original(self) -> None:
        rows = {
            "units": {
                "USD": [
                    {
                        "start": "2022-09-25",
                        "end": "2023-09-30",
                        "val": 100.0,
                        "accn": ACCN_2023,
                        "form": "10-K",
                        "filed": "2023-11-03",
                    },
                    {
                        "start": "2022-09-25",
                        "end": "2023-09-30",
                        "val": 95.0,
                        "accn": ACCN_2024,
                        "form": "10-K",
                        "filed": "2024-11-01",
                    },
                ]
            }
        }
        history = self._history({"NetIncomeLoss": rows})
        assert [v for _, v in history.available_series(Metric.NET_INCOME)] == [95.0]

    def test_tag_priority_falls_back_to_alternatives(self) -> None:
        history = self._history({"Revenues": REVENUE_ROWS})
        assert history.available_series(Metric.REVENUE), "fallback tag must be used"

    def test_legacy_tag_fills_years_missing_from_the_preferred_tag(self) -> None:
        legacy = {
            "units": {
                "USD": [
                    {
                        "start": "2015-09-27",
                        "end": "2016-09-24",
                        "val": 215639000000,
                        "accn": "0000320193-16-000212",
                        "form": "10-K",
                        "filed": "2016-10-26",
                    }
                ]
            }
        }
        history = self._history({REVENUE_TAG: REVENUE_ROWS, "SalesRevenueNet": legacy})
        series = history.available_series(Metric.REVENUE)
        assert [p.label for p, _ in series] == ["FY2016", "FY2023", "FY2024"]

    def test_preferred_tag_wins_when_years_overlap(self) -> None:
        conflicting = {
            "units": {
                "USD": [
                    {
                        "start": "2023-10-01",
                        "end": "2024-09-28",
                        "val": 1.0,
                        "accn": "other",
                        "form": "10-K",
                        "filed": "2024-11-01",
                    }
                ]
            }
        }
        history = self._history({REVENUE_TAG: REVENUE_ROWS, "Revenues": conflicting})
        latest = history.latest(Metric.REVENUE)
        assert latest is not None and latest.value == pytest.approx(391035000000.0)

    def test_absent_metric_is_reported_as_na(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS})
        snapshot = history.sorted_snapshots()[-1]
        assert not snapshot.get(Metric.EBITDA).is_available
        assert history.latest(Metric.EBITDA) is None

    def test_max_periods_limits_history(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS}, max_periods=1)
        assert [s.period.label for s in history.sorted_snapshots()] == ["FY2024"]

    def test_values_carry_verifiable_provenance(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS})
        fact = history.latest(Metric.REVENUE)
        assert fact is not None
        source = fact.sources[0]
        assert fact.kind is FactKind.REPORTED
        assert source.document_id == ACCN_2024
        assert source.locator == f"us-gaap:{REVENUE_TAG}"
        assert source.published_at == date(2024, 11, 1)
        assert source.url is not None and ACCN_2024 in source.url

    def test_currency_is_detected(self) -> None:
        history = self._history({REVENUE_TAG: REVENUE_ROWS})
        assert history.currency == "USD"

    def test_quarterly_period_type_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="fiscal-year"):
            _provider().get_financial_history(APPLE, period_type=PeriodType.QUARTER)

    def test_company_without_cik_is_rejected(self) -> None:
        with pytest.raises(CompanyNotFoundError, match="no CIK"):
            _provider().get_financial_history(Company(name="Unlisted GmbH"))
