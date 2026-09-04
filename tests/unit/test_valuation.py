"""Tests for the valuation engine.

Every expected number is either hand-calculated or an analytically known
identity, so a wrong formula cannot pass unnoticed.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.facts import Confidence, Fact, FactKind, Period, SourceRef, SourceTier
from app.domain.financials import FinancialSnapshot, Metric, NumericFact
from app.services.valuation import (
    DcfAssumptions,
    Multiples,
    compute_multiples,
    run_dcf,
    sensitivity_grid,
)

PERIOD = Period.fiscal_year_of(2025, end=date(2025, 9, 27))
SEC = SourceRef(
    provider="SEC EDGAR", tier=SourceTier.REGULATORY_FILING, document_id="0000320193-25-000079"
)
MARKET = SourceRef(provider="Yahoo Finance", tier=SourceTier.FINANCIAL_DATA_PROVIDER)


def _fact(value: float, *, unit: str = "USD", source: SourceRef = SEC) -> NumericFact:
    return Fact[float](
        value=value,
        unit=unit,
        period=PERIOD,
        kind=FactKind.REPORTED,
        confidence=Confidence.HIGH,
        sources=[source],
    )


class TestAssumptionValidation:
    def test_terminal_growth_above_discount_rate_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must stay below the discount rate"):
            DcfAssumptions(wacc=0.05, terminal_growth=0.06)

    def test_terminal_growth_equal_to_discount_rate_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="perpetuity is infinite"):
            DcfAssumptions(wacc=0.08, terminal_growth=0.08)

    def test_non_positive_discount_rate_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="wacc must be between"):
            DcfAssumptions(wacc=0.0, terminal_growth=-0.01)

    def test_projection_horizon_is_bounded(self) -> None:
        with pytest.raises(ValueError, match="projection_years"):
            DcfAssumptions(wacc=0.08, terminal_growth=0.02, projection_years=99)

    def test_growth_fades_linearly_to_the_terminal_rate(self) -> None:
        path = DcfAssumptions(
            wacc=0.08, terminal_growth=0.02, initial_growth=0.10, projection_years=5
        ).growth_path()
        assert path == pytest.approx((0.10, 0.08, 0.06, 0.04, 0.02))

    def test_growth_is_constant_when_fading_is_off(self) -> None:
        path = DcfAssumptions(
            wacc=0.08, terminal_growth=0.02, initial_growth=0.05, projection_years=3, fade=False
        ).growth_path()
        assert path == pytest.approx((0.05, 0.05, 0.05))


class TestDcfMathematics:
    """A flat perpetuity has a closed form: FCF / (r - g)."""

    def test_single_year_horizon_matches_the_perpetuity_formula(self) -> None:
        assumptions = DcfAssumptions(wacc=0.10, terminal_growth=0.0, projection_years=1)
        result = run_dcf(_fact(100.0), assumptions)
        assert result.enterprise_value.value == pytest.approx(1000.0)

    def test_horizon_length_does_not_change_a_flat_perpetuity(self) -> None:
        short = run_dcf(
            _fact(100.0), DcfAssumptions(wacc=0.10, terminal_growth=0.0, projection_years=1)
        )
        long = run_dcf(
            _fact(100.0),
            DcfAssumptions(
                wacc=0.10, terminal_growth=0.0, projection_years=10, initial_growth=0.0, fade=False
            ),
        )
        assert long.enterprise_value.value == pytest.approx(short.enterprise_value.value)

    def test_growing_perpetuity_matches_the_closed_form(self) -> None:
        # FCF_1 = 100 * 1.03 = 103; value = 103 / (0.09 - 0.03).
        assumptions = DcfAssumptions(
            wacc=0.09, terminal_growth=0.03, projection_years=1, initial_growth=0.03
        )
        result = run_dcf(_fact(100.0), assumptions)
        assert result.enterprise_value.value == pytest.approx(103.0 / 0.06)

    def test_projection_rows_are_discounted_correctly(self) -> None:
        assumptions = DcfAssumptions(
            wacc=0.10, terminal_growth=0.0, projection_years=3, initial_growth=0.0, fade=False
        )
        years = run_dcf(_fact(100.0), assumptions).years
        assert [year.year for year in years] == [1, 2, 3]
        assert years[0].present_value == pytest.approx(100 / 1.10)
        assert years[2].present_value == pytest.approx(100 / 1.10**3)

    def test_higher_discount_rate_lowers_the_value(self) -> None:
        cheap = run_dcf(_fact(100.0), DcfAssumptions(wacc=0.07, terminal_growth=0.02))
        dear = run_dcf(_fact(100.0), DcfAssumptions(wacc=0.11, terminal_growth=0.02))
        assert cheap.enterprise_value.value is not None
        assert dear.enterprise_value.value is not None
        assert cheap.enterprise_value.value > dear.enterprise_value.value

    def test_terminal_share_is_reported(self) -> None:
        assumptions = DcfAssumptions(
            wacc=0.10, terminal_growth=0.0, projection_years=5, initial_growth=0.0, fade=False
        )
        result = run_dcf(_fact(100.0), assumptions)
        assert result.terminal_value_share == pytest.approx(1 / 1.10**5, rel=1e-6)


class TestEquityBridge:
    def test_net_debt_is_subtracted(self) -> None:
        result = run_dcf(
            _fact(100.0),
            DcfAssumptions(wacc=0.10, terminal_growth=0.0, projection_years=1),
            net_debt=_fact(200.0),
            shares_outstanding=_fact(100.0, unit="shares"),
        )
        assert result.equity_value.value == pytest.approx(800.0)
        assert result.value_per_share.value == pytest.approx(8.0)

    def test_net_cash_increases_equity_value(self) -> None:
        result = run_dcf(
            _fact(100.0),
            DcfAssumptions(wacc=0.10, terminal_growth=0.0, projection_years=1),
            net_debt=_fact(-150.0),
        )
        assert result.equity_value.value == pytest.approx(1150.0)

    def test_missing_net_debt_blocks_equity_value_but_not_enterprise_value(self) -> None:
        result = run_dcf(
            _fact(100.0), DcfAssumptions(wacc=0.10, terminal_growth=0.0, projection_years=1)
        )
        assert result.enterprise_value.is_available
        assert not result.equity_value.is_available
        assert not result.value_per_share.is_available

    def test_missing_share_count_blocks_only_the_per_share_value(self) -> None:
        result = run_dcf(
            _fact(100.0),
            DcfAssumptions(wacc=0.10, terminal_growth=0.0, projection_years=1),
            net_debt=_fact(200.0),
        )
        assert result.equity_value.is_available
        assert not result.value_per_share.is_available


class TestRefusalToGuess:
    def test_missing_cash_flow_yields_no_valuation(self) -> None:
        result = run_dcf(Fact.not_available(), DcfAssumptions(wacc=0.08, terminal_growth=0.02))
        assert not result.is_available
        assert result.years == ()
        assert result.enterprise_value.display() == "DATA NOT AVAILABLE"

    def test_negative_cash_flow_is_refused_rather_than_extrapolated(self) -> None:
        result = run_dcf(_fact(-50.0), DcfAssumptions(wacc=0.08, terminal_growth=0.02))
        assert not result.is_available
        assert result.enterprise_value.note is not None
        assert "not positive" in result.enterprise_value.note


class TestResultIsMarkedAsAssumption:
    def _result(self) -> NumericFact:
        return run_dcf(
            _fact(100.0),
            DcfAssumptions(
                wacc=0.10,
                terminal_growth=0.0,
                projection_years=5,
                fade=False,
                rationale="test",
            ),
        ).enterprise_value

    def test_kind_is_assumption_not_reported(self) -> None:
        assert self._result().kind is FactKind.ASSUMPTION

    def test_display_flags_the_value_as_an_assumption(self) -> None:
        assert "[ASSUMPTION]" in self._result().display()

    def test_note_uses_the_required_conditional_wording(self) -> None:
        note = self._result().note
        assert note is not None and note.startswith("Auf Basis der verwendeten Annahmen")

    def test_note_states_the_driving_assumptions(self) -> None:
        note = self._result().note
        assert note is not None
        assert "WACC 10.0%" in note
        assert "terminal growth 0.0%" in note

    def test_underlying_data_source_remains_traceable(self) -> None:
        providers = {source.provider for source in self._result().sources}
        assert "SEC EDGAR" in providers
        assert "finance_agents/model" in providers

    def test_confidence_never_exceeds_medium(self) -> None:
        assert self._result().confidence is Confidence.MEDIUM

    def test_terminal_dominated_result_is_downgraded(self) -> None:
        result = run_dcf(
            _fact(100.0),
            DcfAssumptions(
                wacc=0.06, terminal_growth=0.04, initial_growth=0.04, projection_years=5
            ),
        )
        assert result.terminal_value_share is not None
        assert result.terminal_value_share > 0.75
        assert result.enterprise_value.confidence is Confidence.LOW


class TestSensitivityGrid:
    def test_default_ranges_cover_the_documented_span(self) -> None:
        grid = sensitivity_grid(
            _fact(100.0),
            DcfAssumptions(wacc=0.08, terminal_growth=0.02, projection_years=1),
            net_debt=_fact(0.0),
            shares_outstanding=_fact(100.0, unit="shares"),
        )
        assert grid.waccs[0] == pytest.approx(0.05)
        assert grid.waccs[-1] == pytest.approx(0.12)
        assert grid.terminal_growths == pytest.approx((0.01, 0.02, 0.03, 0.04))
        assert len(grid.values) == len(grid.waccs)
        assert all(len(row) == len(grid.terminal_growths) for row in grid.values)

    def test_cell_matches_a_direct_calculation(self) -> None:
        grid = sensitivity_grid(
            _fact(100.0),
            DcfAssumptions(wacc=0.08, terminal_growth=0.02, projection_years=1),
            net_debt=_fact(0.0),
            shares_outstanding=_fact(100.0, unit="shares"),
        )
        direct = run_dcf(
            _fact(100.0),
            DcfAssumptions(wacc=0.09, terminal_growth=0.03, projection_years=1, initial_growth=0.0),
            net_debt=_fact(0.0),
            shares_outstanding=_fact(100.0, unit="shares"),
        )
        assert grid.value_at(0.09, 0.03) == pytest.approx(direct.value_per_share.value)

    def test_undefined_combinations_are_empty_not_zero(self) -> None:
        grid = sensitivity_grid(
            _fact(100.0),
            DcfAssumptions(wacc=0.08, terminal_growth=0.02, projection_years=1),
            net_debt=_fact(0.0),
            shares_outstanding=_fact(100.0, unit="shares"),
            waccs=(0.03, 0.08),
            terminal_growths=(0.04,),
        )
        assert grid.value_at(0.03, 0.04) is None
        assert grid.value_at(0.08, 0.04) is not None

    def test_values_fall_as_the_discount_rate_rises(self) -> None:
        grid = sensitivity_grid(
            _fact(100.0),
            DcfAssumptions(wacc=0.08, terminal_growth=0.02, projection_years=1),
            net_debt=_fact(0.0),
            shares_outstanding=_fact(100.0, unit="shares"),
        )
        column = [row[1] for row in grid.values if row[1] is not None]
        assert len(column) == len(grid.values), "every default combination must be defined"
        assert column == sorted(column, reverse=True)

    def test_spread_reports_the_range_of_outcomes(self) -> None:
        grid = sensitivity_grid(
            _fact(100.0),
            DcfAssumptions(wacc=0.08, terminal_growth=0.02, projection_years=1),
            net_debt=_fact(0.0),
            shares_outstanding=_fact(100.0, unit="shares"),
        )
        spread = grid.spread()
        assert spread is not None
        low, high = spread
        assert low < high


class TestMultiples:
    def _snapshot(self, overrides: dict[Metric, NumericFact] | None = None) -> FinancialSnapshot:
        values: dict[Metric, NumericFact] = {
            Metric.SHARES_OUTSTANDING: _fact(1_000.0, unit="shares"),
            Metric.NET_DEBT: _fact(50_000.0),
            Metric.EPS_DILUTED: _fact(10.0),
            Metric.FREE_CASH_FLOW: _fact(25_000.0),
            Metric.TOTAL_EQUITY: _fact(125_000.0),
            Metric.EBITDA: _fact(30_000.0),
            Metric.REVENUE: _fact(100_000.0),
        }
        values.update(overrides or {})
        return FinancialSnapshot(period=PERIOD, values=values)

    def _multiples(self, overrides: dict[Metric, NumericFact] | None = None) -> Multiples:
        return compute_multiples(_fact(250.0, source=MARKET), self._snapshot(overrides))

    def test_market_cap_and_enterprise_value(self) -> None:
        multiples = self._multiples()
        assert multiples.market_cap.value == pytest.approx(250_000.0)
        assert multiples.enterprise_value.value == pytest.approx(300_000.0)

    @pytest.mark.parametrize(
        ("attribute", "expected"),
        [
            ("price_earnings", 25.0),
            ("price_free_cash_flow", 10.0),
            ("price_book", 2.0),
            ("ev_ebitda", 10.0),
            ("ev_sales", 3.0),
        ],
    )
    def test_ratios(self, attribute: str, expected: float) -> None:
        assert getattr(self._multiples(), attribute).value == pytest.approx(expected)

    def test_negative_earnings_yield_no_price_earnings_ratio(self) -> None:
        multiples = self._multiples({Metric.EPS_DILUTED: _fact(-5.0)})
        assert not multiples.price_earnings.is_available

    def test_multiples_cite_both_price_and_fundamentals(self) -> None:
        providers = {source.provider for source in self._multiples().ev_sales.sources}
        assert providers == {"Yahoo Finance", "SEC EDGAR"}

    def test_note_records_the_reporting_period_mismatch(self) -> None:
        note = self._multiples().ev_sales.note
        assert note is not None and "FY2025" in note

    def test_missing_fundamentals_do_not_produce_a_number(self) -> None:
        snapshot = FinancialSnapshot(
            period=PERIOD, values={Metric.SHARES_OUTSTANDING: _fact(1_000.0, unit="shares")}
        )
        multiples = compute_multiples(_fact(250.0, source=MARKET), snapshot)
        assert multiples.market_cap.is_available
        assert not multiples.enterprise_value.is_available
        assert not multiples.ev_ebitda.is_available
