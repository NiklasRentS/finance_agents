"""Tests for the analysis orchestration and the Markdown report."""

from __future__ import annotations

import pytest

from app.domain.financials import Metric
from app.ports.market_data import MarketDataProvider
from app.reporting.markdown import DISCLAIMER, NOT_AVAILABLE, render_markdown
from app.services.analysis import DEFAULT_ASSUMPTIONS, CompanyAnalysis, analyse_company
from app.services.valuation import DcfAssumptions
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


def _analysis(
    *,
    omit: set[Metric] | None = None,
    market: MarketDataProvider | None = None,
    assumptions: DcfAssumptions = DEFAULT_ASSUMPTIONS,
) -> CompanyAnalysis:
    return analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(omit=omit),
        market_data=market if market is not None else ConfigurableFakeMarketData(),
        assumptions=assumptions,
    )


class TestAnalysisOrchestration:
    def test_company_and_periods_are_resolved(self) -> None:
        analysis = _analysis()
        assert analysis.company.name == "Example Corp."
        assert analysis.ticker == "EXMP"
        assert len(analysis.history.snapshots) == 3

    def test_derived_metrics_are_added(self) -> None:
        latest = _analysis().latest
        assert latest is not None
        assert latest.get(Metric.FREE_CASH_FLOW).is_available
        assert latest.get(Metric.ROIC).is_available

    def test_trends_are_computed_for_every_tracked_metric(self) -> None:
        analysis = _analysis()
        assert analysis.trends
        assert all(trend.periods >= 0 for trend in analysis.trends.values())

    def test_valuation_and_sensitivity_are_produced(self) -> None:
        analysis = _analysis()
        assert analysis.valuation.is_available
        assert analysis.valuation.value_per_share.is_available
        assert len(analysis.sensitivity.values) == len(analysis.sensitivity.waccs)

    def test_multiples_use_the_quote(self) -> None:
        analysis = _analysis()
        assert analysis.multiples is not None
        assert analysis.multiples.market_cap.is_available


class TestDegradesInsteadOfFailing:
    def test_market_data_outage_is_recorded_but_not_fatal(self) -> None:
        analysis = _analysis(market=ConfigurableFakeMarketData(fail=True))
        assert analysis.quote is None
        assert analysis.multiples is None
        assert any("Marktdaten" in warning for warning in analysis.warnings)
        assert analysis.valuation.is_available, "fundamentals valuation must survive"

    def test_analysis_without_market_provider(self) -> None:
        analysis = analyse_company(
            "EXMP", fundamentals=CompleteFakeFundamentals(), market_data=None
        )
        assert analysis.quote is None
        assert analysis.history.snapshots

    def test_missing_cash_flow_is_reported_as_a_warning(self) -> None:
        analysis = _analysis(omit={Metric.OPERATING_CASH_FLOW})
        assert any("Free Cash Flow" in warning for warning in analysis.warnings)
        assert not analysis.valuation.is_available

    def test_missing_metrics_are_listed(self) -> None:
        analysis = _analysis(omit={Metric.EPS_DILUTED})
        assert Metric.EPS_DILUTED in analysis.missing_metrics()


class TestMarkdownReport:
    def test_report_starts_with_the_company_name(self) -> None:
        assert render_markdown(_analysis()).startswith("# Fundamentalanalyse: Example Corp.")

    def test_disclaimer_is_present(self) -> None:
        assert DISCLAIMER in render_markdown(_analysis())

    def test_expected_sections_are_present(self) -> None:
        report = render_markdown(_analysis())
        for heading in (
            "## Kennzahlen",
            "## Margen und Renditen",
            "## Historie",
            "## Entwicklung",
            "## Marktdaten",
            "## Bewertung (DCF)",
            "## Sensitivitaet",
            "## Datenluecken",
            "## Quellen",
        ):
            assert heading in report, f"missing section {heading}"

    def test_valuation_is_flagged_as_an_assumption(self) -> None:
        report = render_markdown(_analysis())
        assert "[ASSUMPTION]" in report
        assert "Annahmen: WACC" in report

    def test_sources_are_numbered_and_referenced(self) -> None:
        report = render_markdown(_analysis())
        assert "[1]" in report
        assert "SEC EDGAR" in report
        assert "https://www.sec.gov/example" in report

    def test_missing_values_are_named_not_omitted(self) -> None:
        report = render_markdown(_analysis(omit={Metric.EPS_DILUTED}))
        assert NOT_AVAILABLE in report
        gaps = report.split("## Datenluecken")[1]
        assert "Ergebnis je Aktie" in gaps

    def test_report_without_market_data_still_renders(self) -> None:
        report = render_markdown(_analysis(market=ConfigurableFakeMarketData(fail=True)))
        assert "## Marktdaten" in report
        assert NOT_AVAILABLE in report

    def test_sensitivity_table_has_one_row_per_discount_rate(self) -> None:
        analysis = _analysis()
        report = render_markdown(analysis)
        table = report.split("## Sensitivitaet")[1]
        for wacc in analysis.sensitivity.waccs:
            assert f"| {wacc:.1%} |" in table

    def test_report_ends_with_a_single_newline(self) -> None:
        report = render_markdown(_analysis())
        assert report.endswith("\n")
        assert not report.endswith("\n\n")

    @pytest.mark.parametrize("omit", [set(), {Metric.SHARES_OUTSTANDING}, {Metric.LONG_TERM_DEBT}])
    def test_rendering_never_raises_on_incomplete_data(self, omit: set[Metric]) -> None:
        assert render_markdown(_analysis(omit=omit))


class TestUnitsAreNotConfused:
    """Money, per-share amounts and share counts must not share one formatter."""

    def _row(self, label: str) -> str:
        report = render_markdown(_analysis())
        return next(line for line in report.splitlines() if line.startswith(f"| {label} |"))

    def test_per_share_amounts_keep_their_precision(self) -> None:
        # 6.50 in the base year, grown by 8% for each of the two later years.
        assert "| 7.54 USD |" in self._row("Ergebnis je Aktie (verwaessert)")

    def test_share_counts_are_not_labelled_as_currency(self) -> None:
        row = self._row("Ausstehende Aktien")
        assert "Stueck" in row
        assert "USD" not in row

    def test_money_stays_in_millions(self) -> None:
        assert "Mio. USD" in self._row("Umsatz")

    def test_repeated_sources_produce_one_marker(self) -> None:
        row = self._row("Free Cash Flow")
        assert "[1][1]" not in row, "the same document must be cited once"
        assert "[1]" in row
