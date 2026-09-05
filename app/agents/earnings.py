"""Delta analysis for the last reported periods.

The agent compares the latest complete period with the prior period for the same
metric and reports the absolute difference, the percentage change, and the
underlying fact sources. It never invents a change when a prior fact is missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.financials import Metric, NumericFact
from app.services.analysis import CompanyAnalysis


@dataclass(frozen=True)
class EarningsDelta:
    metric: Metric
    current: NumericFact
    previous: NumericFact
    delta: float
    pct_change: float


def build_earnings_delta(analysis: CompanyAnalysis) -> list[EarningsDelta]:
    """Compare the latest available period against the prior one for each metric."""
    snapshots = analysis.history.sorted_snapshots()
    if len(snapshots) < 2:
        return []

    latest = snapshots[-1]
    previous = snapshots[-2]
    deltas: list[EarningsDelta] = []
    for metric in (
        Metric.REVENUE,
        Metric.GROSS_PROFIT,
        Metric.OPERATING_INCOME,
        Metric.NET_INCOME,
        Metric.EPS_DILUTED,
        Metric.FREE_CASH_FLOW,
        Metric.SHARES_DILUTED,
    ):
        current_fact = latest.get(metric)
        previous_fact = previous.get(metric)
        if not current_fact.is_available or not previous_fact.is_available:
            continue
        if current_fact.value is None or previous_fact.value is None:
            continue
        if previous_fact.value == 0:
            pct_change = 0.0
        else:
            pct_change = (current_fact.value - previous_fact.value) / previous_fact.value
        deltas.append(
            EarningsDelta(
                metric=metric,
                current=current_fact,
                previous=previous_fact,
                delta=current_fact.value - previous_fact.value,
                pct_change=pct_change,
            )
        )
    return deltas
