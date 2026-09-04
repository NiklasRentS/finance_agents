"""Tests for derived metrics.

Numbers are chosen so every expected result can be verified by hand.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.facts import Confidence, Fact, FactKind, Period, SourceRef, SourceTier
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric, NumericFact
from app.services.metrics import (
    TrendDirection,
    analyse_trend,
    cagr,
    combined_confidence,
    enrich,
    market_capitalisation,
    merge_sources,
)

SEC = SourceRef(
    provider="SEC EDGAR", tier=SourceTier.REGULATORY_FILING, document_id="A", locator="x"
)
OTHER = SourceRef(
    provider="SEC EDGAR", tier=SourceTier.REGULATORY_FILING, document_id="B", locator="y"
)

BASE_FIGURES: dict[Metric, float] = {
    Metric.REVENUE: 1000.0,
    Metric.COST_OF_REVENUE: 600.0,
    Metric.OPERATING_INCOME: 100.0,
    Metric.DEPRECIATION_AMORTIZATION: 50.0,
    Metric.NET_INCOME: 60.0,
    Metric.OPERATING_CASH_FLOW: 120.0,
    Metric.CAPITAL_EXPENDITURE: 30.0,
    Metric.CASH_AND_EQUIVALENTS: 100.0,
    Metric.SHORT_TERM_INVESTMENTS: 50.0,
    Metric.SHORT_TERM_DEBT: 50.0,
    Metric.LONG_TERM_DEBT: 150.0,
    Metric.TOTAL_EQUITY: 400.0,
    Metric.INCOME_TAX_EXPENSE: 20.0,
    Metric.PRETAX_INCOME: 80.0,
    Metric.TOTAL_CURRENT_ASSETS: 300.0,
    Metric.TOTAL_CURRENT_LIABILITIES: 120.0,
}


def _fact(value: float, period: Period, unit: str = "USD") -> NumericFact:
    return Fact[float](
        value=value,
        unit=unit,
        period=period,
        kind=FactKind.REPORTED,
        confidence=Confidence.HIGH,
        sources=[SEC],
    )


def _snapshot(year: int, figures: dict[Metric, float]) -> FinancialSnapshot:
    period = Period.fiscal_year_of(year, end=date(year, 12, 31))
    return FinancialSnapshot(
        period=period,
        values={metric: _fact(value, period) for metric, value in figures.items()},
    )


def _enriched(figures: dict[Metric, float] | None = None) -> FinancialSnapshot:
    history = enrich(FinancialHistory(snapshots=[_snapshot(2024, figures or BASE_FIGURES)]))
    return history.sorted_snapshots()[0]


class TestDerivedValues:
    @pytest.mark.parametrize(
        ("metric", "expected"),
        [
            (Metric.GROSS_PROFIT, 400.0),
            (Metric.EBIT, 100.0),
            (Metric.EBITDA, 150.0),
            (Metric.FREE_CASH_FLOW, 90.0),
            (Metric.TOTAL_DEBT, 200.0),
            (Metric.NET_DEBT, 50.0),
            (Metric.WORKING_CAPITAL, 180.0),
            (Metric.INVESTED_CAPITAL, 500.0),
        ],
    )
    def test_absolute_metrics(self, metric: Metric, expected: float) -> None:
        assert _enriched().get(metric).value == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("metric", "expected"),
        [
            (Metric.GROSS_MARGIN, 0.40),
            (Metric.OPERATING_MARGIN, 0.10),
            (Metric.EBITDA_MARGIN, 0.15),
            (Metric.NET_MARGIN, 0.06),
            (Metric.FCF_MARGIN, 0.09),
            (Metric.ROE, 0.15),
            (Metric.ROIC, 0.15),
        ],
    )
    def test_ratios(self, metric: Metric, expected: float) -> None:
        fact = _enriched().get(metric)
        assert fact.value == pytest.approx(expected)
        assert fact.unit == "ratio"

    def test_derived_values_are_marked_as_derived(self) -> None:
        fact = _enriched().get(Metric.FREE_CASH_FLOW)
        assert fact.kind is FactKind.DERIVED
        assert fact.note is not None and "operating cash flow" in fact.note

    def test_money_metrics_inherit_the_input_unit(self) -> None:
        assert _enriched().get(Metric.FREE_CASH_FLOW).unit == "USD"


class TestMissingDataIsNeverInvented:
    def test_missing_input_yields_na(self) -> None:
        figures: dict[Metric, float] = {
            k: v for k, v in BASE_FIGURES.items() if k is not Metric.CAPITAL_EXPENDITURE
        }
        fact = _enriched(figures).get(Metric.FREE_CASH_FLOW)
        assert not fact.is_available
        assert fact.display() == "DATA NOT AVAILABLE"
        assert fact.note is not None and "input missing" in fact.note

    def test_missing_debt_component_blocks_net_debt(self) -> None:
        figures: dict[Metric, float] = {
            k: v for k, v in BASE_FIGURES.items() if k is not Metric.SHORT_TERM_DEBT
        }
        snapshot = _enriched(figures)
        assert not snapshot.get(Metric.TOTAL_DEBT).is_available
        assert not snapshot.get(Metric.NET_DEBT).is_available

    def test_zero_denominator_yields_na(self) -> None:
        figures = {**BASE_FIGURES, Metric.REVENUE: 0.0}
        fact = _enriched(figures).get(Metric.GROSS_MARGIN)
        assert not fact.is_available
        assert fact.note is not None and "undefined" in fact.note

    def test_roic_is_na_when_pretax_income_is_negative(self) -> None:
        figures = {**BASE_FIGURES, Metric.PRETAX_INCOME: -10.0}
        assert not _enriched(figures).get(Metric.ROIC).is_available

    def test_reported_value_is_not_overwritten(self) -> None:
        figures = {**BASE_FIGURES, Metric.GROSS_PROFIT: 123.0}
        fact = _enriched(figures).get(Metric.GROSS_PROFIT)
        assert fact.value == pytest.approx(123.0)
        assert fact.kind is FactKind.REPORTED


class TestProvenancePropagation:
    def test_sources_of_all_inputs_are_carried_over(self) -> None:
        period = Period.fiscal_year_of(2024)
        a = Fact[float](value=10.0, period=period, kind=FactKind.REPORTED, sources=[SEC])
        b = Fact[float](value=4.0, period=period, kind=FactKind.REPORTED, sources=[OTHER])
        assert len(merge_sources([a, b])) == 2

    def test_duplicate_sources_are_collapsed(self) -> None:
        a = Fact[float](value=1.0, kind=FactKind.REPORTED, sources=[SEC])
        b = Fact[float](value=2.0, kind=FactKind.REPORTED, sources=[SEC])
        assert len(merge_sources([a, b])) == 1

    def test_derived_fact_cites_its_inputs(self) -> None:
        fact = _enriched().get(Metric.GROSS_MARGIN)
        assert fact.sources, "derived ratios must remain traceable"

    def test_confidence_follows_the_weakest_input(self) -> None:
        strong = Fact.derived(1.0, confidence=Confidence.HIGH)
        weak = Fact.derived(1.0, confidence=Confidence.LOW)
        assert combined_confidence([strong, weak]) is Confidence.LOW

    def test_confidence_of_uniform_inputs_is_preserved(self) -> None:
        facts = [Fact.derived(1.0, confidence=Confidence.HIGH) for _ in range(3)]
        assert combined_confidence(facts) is Confidence.HIGH


class TestRevenueGrowth:
    def test_growth_is_computed_between_periods(self) -> None:
        history = enrich(
            FinancialHistory(
                snapshots=[
                    _snapshot(2023, {Metric.REVENUE: 1000.0}),
                    _snapshot(2024, {Metric.REVENUE: 1200.0}),
                ]
            )
        )
        snapshots = history.sorted_snapshots()
        assert not snapshots[0].get(Metric.REVENUE_GROWTH).is_available
        assert snapshots[1].get(Metric.REVENUE_GROWTH).value == pytest.approx(0.20)

    def test_declining_revenue_yields_negative_growth(self) -> None:
        history = enrich(
            FinancialHistory(
                snapshots=[
                    _snapshot(2023, {Metric.REVENUE: 1000.0}),
                    _snapshot(2024, {Metric.REVENUE: 900.0}),
                ]
            )
        )
        growth = history.sorted_snapshots()[1].get(Metric.REVENUE_GROWTH)
        assert growth.value == pytest.approx(-0.10)


class TestCagrAndTrend:
    def test_cagr_matches_manual_calculation(self) -> None:
        assert cagr(100.0, 121.0, 2.0) == pytest.approx(0.10)

    def test_cagr_is_undefined_for_negative_start(self) -> None:
        assert cagr(-5.0, 10.0, 3.0) is None

    def test_cagr_is_undefined_without_elapsed_time(self) -> None:
        assert cagr(100.0, 121.0, 0.0) is None

    def _history(self, values: list[float]) -> FinancialHistory:
        return FinancialHistory(
            snapshots=[
                _snapshot(2020 + index, {Metric.REVENUE: value})
                for index, value in enumerate(values)
            ]
        )

    def test_rising_series_is_detected(self) -> None:
        summary = analyse_trend(self._history([100.0, 110.0, 125.0, 140.0]), Metric.REVENUE)
        assert summary.direction is TrendDirection.RISING
        assert summary.periods == 4
        assert summary.cagr.is_available

    def test_falling_series_is_detected(self) -> None:
        summary = analyse_trend(self._history([140.0, 125.0, 110.0, 100.0]), Metric.REVENUE)
        assert summary.direction is TrendDirection.FALLING

    def test_flat_series_is_stable(self) -> None:
        summary = analyse_trend(self._history([100.0, 100.5, 99.8, 100.2]), Metric.REVENUE)
        assert summary.direction is TrendDirection.STABLE

    def test_single_observation_has_unknown_direction(self) -> None:
        summary = analyse_trend(self._history([100.0]), Metric.REVENUE)
        assert summary.direction is TrendDirection.UNKNOWN
        assert not summary.cagr.is_available

    def test_trend_cagr_cites_its_endpoints(self) -> None:
        summary = analyse_trend(self._history([100.0, 121.0]), Metric.REVENUE)
        assert summary.cagr.sources


class TestSplitDiscontinuities:
    """As-filed share counts jump at a stock split and must not be compared blindly."""

    def _history(self, shares: list[float]) -> FinancialHistory:
        return enrich(
            FinancialHistory(
                snapshots=[
                    _snapshot(2018 + index, {Metric.SHARES_DILUTED: value})
                    for index, value in enumerate(shares)
                ]
            )
        )

    def test_pre_split_values_are_downgraded(self) -> None:
        # 4:1 split between the second and third period, as Apple did in 2020.
        history = self._history([5_200.0, 5_000.0, 17_500.0, 16_800.0])
        facts = [snapshot.get(Metric.SHARES_DILUTED) for snapshot in history.sorted_snapshots()]
        assert [fact.confidence for fact in facts[:2]] == [Confidence.LOW, Confidence.LOW]
        assert facts[0].note is not None and "not split-adjusted" in facts[0].note
        assert facts[2].confidence is Confidence.HIGH

    def test_downgraded_facts_keep_their_value_and_sources(self) -> None:
        history = self._history([5_200.0, 5_000.0, 17_500.0])
        fact = history.sorted_snapshots()[0].get(Metric.SHARES_DILUTED)
        assert fact.value == pytest.approx(5_200.0)
        assert fact.sources == [SEC]
        assert "LOW CONFIDENCE" in fact.display()

    def test_buyback_series_is_left_untouched(self) -> None:
        history = self._history([17_000.0, 16_400.0, 15_800.0, 15_200.0])
        facts = [snapshot.get(Metric.SHARES_DILUTED) for snapshot in history.sorted_snapshots()]
        assert all(fact.confidence is Confidence.HIGH for fact in facts)
        assert all(fact.note is None for fact in facts)

    def test_trend_across_a_split_is_unknown_instead_of_misleading(self) -> None:
        history = self._history([5_200.0, 5_000.0, 17_500.0, 16_800.0])
        summary = analyse_trend(history, Metric.SHARES_DILUTED)
        assert summary.direction is TrendDirection.UNKNOWN
        assert not summary.cagr.is_available

    def test_buyback_trend_is_still_reported_as_falling(self) -> None:
        history = self._history([17_000.0, 16_400.0, 15_800.0, 15_200.0])
        summary = analyse_trend(history, Metric.SHARES_DILUTED)
        assert summary.direction is TrendDirection.FALLING

    def test_other_metrics_may_jump_freely(self) -> None:
        history = enrich(
            FinancialHistory(
                snapshots=[
                    _snapshot(2020, {Metric.REVENUE: 1000.0}),
                    _snapshot(2021, {Metric.REVENUE: 2000.0}),
                ]
            )
        )
        summary = analyse_trend(history, Metric.REVENUE)
        assert summary.direction is TrendDirection.RISING
        assert summary.cagr.is_available


class TestMarketCapitalisation:
    def test_price_times_shares(self) -> None:
        period = Period.fiscal_year_of(2024)
        price = Fact[float](value=250.0, unit="USD", kind=FactKind.REPORTED, sources=[SEC])
        shares = Fact[float](
            value=15_000_000_000.0,
            unit="shares",
            period=period,
            kind=FactKind.REPORTED,
            sources=[OTHER],
        )
        cap = market_capitalisation(price, shares)
        assert cap.value == pytest.approx(3.75e12)
        assert cap.unit == "USD"
        assert len(cap.sources) == 2, "market cap must cite both price and share count"

    def test_missing_share_count_yields_na(self) -> None:
        price = Fact[float](value=250.0, unit="USD", kind=FactKind.REPORTED, sources=[SEC])
        assert not market_capitalisation(price, Fact.not_available()).is_available
