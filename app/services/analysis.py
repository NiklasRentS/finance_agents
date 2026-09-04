"""Orchestration of one research run for a single company.

This is the seam the agents will later plug into: it collects data, derives
metrics and values the company, but makes no judgement about the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.company import Company
from app.domain.facts import Fact
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric
from app.infra.logging import get_logger
from app.ports.exceptions import ProviderError
from app.ports.fundamentals import FundamentalsProvider
from app.ports.market_data import MarketDataProvider, Quote
from app.services.metrics import TrendSummary, analyse_trend, enrich
from app.services.valuation import (
    DcfAssumptions,
    DcfResult,
    Multiples,
    SensitivityGrid,
    compute_multiples,
    run_dcf,
    sensitivity_grid,
)

logger = get_logger(__name__)

TREND_METRICS: tuple[Metric, ...] = (
    Metric.REVENUE,
    Metric.GROSS_MARGIN,
    Metric.OPERATING_MARGIN,
    Metric.NET_INCOME,
    Metric.FREE_CASH_FLOW,
    Metric.ROIC,
    Metric.TOTAL_DEBT,
    Metric.SHARES_DILUTED,
)

HEADLINE_METRICS: tuple[Metric, ...] = (
    Metric.REVENUE,
    Metric.GROSS_PROFIT,
    Metric.OPERATING_INCOME,
    Metric.EBITDA,
    Metric.NET_INCOME,
    Metric.EPS_DILUTED,
    Metric.OPERATING_CASH_FLOW,
    Metric.CAPITAL_EXPENDITURE,
    Metric.FREE_CASH_FLOW,
    Metric.TOTAL_ASSETS,
    Metric.TOTAL_EQUITY,
    Metric.TOTAL_DEBT,
    Metric.NET_DEBT,
    Metric.SHARES_OUTSTANDING,
)

RATIO_METRICS: tuple[Metric, ...] = (
    Metric.REVENUE_GROWTH,
    Metric.GROSS_MARGIN,
    Metric.OPERATING_MARGIN,
    Metric.EBITDA_MARGIN,
    Metric.NET_MARGIN,
    Metric.FCF_MARGIN,
    Metric.ROE,
    Metric.ROIC,
)

DEFAULT_ASSUMPTIONS = DcfAssumptions(
    wacc=0.09,
    terminal_growth=0.02,
    initial_growth=0.04,
    projection_years=5,
    rationale=(
        "Platzhalterannahmen, nicht unternehmensspezifisch hergeleitet. "
        "Vor jeder Verwendung durch eigene Werte ersetzen."
    ),
)


@dataclass(frozen=True)
class CompanyAnalysis:
    company: Company
    ticker: str
    generated_at: datetime
    history: FinancialHistory
    trends: dict[Metric, TrendSummary]
    assumptions: DcfAssumptions
    valuation: DcfResult
    sensitivity: SensitivityGrid
    quote: Quote | None = None
    multiples: Multiples | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def latest(self) -> FinancialSnapshot | None:
        snapshots = self.history.sorted_snapshots()
        return snapshots[-1] if snapshots else None

    def missing_metrics(self) -> list[Metric]:
        """Metrics the report asked for but could not obtain, in report order."""
        snapshot = self.latest
        if snapshot is None:
            return list(HEADLINE_METRICS) + list(RATIO_METRICS)
        return [
            metric
            for metric in (*HEADLINE_METRICS, *RATIO_METRICS)
            if not snapshot.get(metric).is_available
        ]


def analyse_company(
    ticker: str,
    *,
    fundamentals: FundamentalsProvider,
    market_data: MarketDataProvider | None = None,
    assumptions: DcfAssumptions = DEFAULT_ASSUMPTIONS,
    max_periods: int = 10,
) -> CompanyAnalysis:
    """Run the deterministic part of a research report end to end."""
    warnings: list[str] = []
    company = fundamentals.resolve_company(ticker)
    history = enrich(fundamentals.get_financial_history(company, max_periods=max_periods))
    snapshot = history.sorted_snapshots()[-1] if history.snapshots else None
    if snapshot is None:
        warnings.append("Keine Berichtsperioden gefunden.")

    trends = {metric: analyse_trend(history, metric) for metric in TREND_METRICS}

    base_fcf = history.latest(Metric.FREE_CASH_FLOW)
    net_debt = history.latest(Metric.NET_DEBT)
    shares = history.latest(Metric.SHARES_OUTSTANDING)
    if base_fcf is None or not base_fcf.is_available:
        warnings.append("Kein Free Cash Flow verfuegbar, DCF nicht berechenbar.")
    if net_debt is None or not net_debt.is_available:
        warnings.append("Nettoverschuldung nicht verfuegbar, Eigenkapitalwert nicht ableitbar.")

    fcf_fact = base_fcf if base_fcf is not None else Fact[float].not_available()
    valuation = run_dcf(fcf_fact, assumptions, net_debt=net_debt, shares_outstanding=shares)
    sensitivity = sensitivity_grid(
        fcf_fact, assumptions, net_debt=net_debt, shares_outstanding=shares
    )

    quote, multiples = _market_section(ticker, market_data, snapshot, warnings)

    return CompanyAnalysis(
        company=company,
        ticker=ticker.strip().upper(),
        generated_at=datetime.now(UTC),
        history=history,
        trends=trends,
        assumptions=assumptions,
        valuation=valuation,
        sensitivity=sensitivity,
        quote=quote,
        multiples=multiples,
        warnings=tuple(warnings),
    )


def _market_section(
    ticker: str,
    market_data: MarketDataProvider | None,
    snapshot: FinancialSnapshot | None,
    warnings: list[str],
) -> tuple[Quote | None, Multiples | None]:
    """Price data is optional: a fundamentals report stays valid without it."""
    if market_data is None or snapshot is None:
        return None, None
    try:
        quote = market_data.get_quote(ticker)
    except ProviderError as exc:
        logger.warning("analysis.market_data_failed", ticker=ticker, error=str(exc))
        warnings.append(f"Marktdaten nicht verfuegbar: {exc}")
        return None, None
    return quote, compute_multiples(quote.price, snapshot)
