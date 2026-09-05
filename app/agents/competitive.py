from __future__ import annotations

from dataclasses import dataclass

from app.domain.financials import Metric
from app.services.analysis import CompanyAnalysis


@dataclass(frozen=True)
class CompetitiveSummary:
    score: float
    summary: str


def build_competitive_summary(analysis: CompanyAnalysis) -> CompetitiveSummary:
    latest = analysis.latest
    if latest is None:
        return CompetitiveSummary(score=0.0, summary="Keine aktuelle Berichtsperiode vorhanden.")

    revenue = latest.get(Metric.REVENUE)
    margin = latest.get(Metric.GROSS_MARGIN)
    roe = latest.get(Metric.ROE)

    score = 50.0
    if revenue.is_available and revenue.value is not None:
        score += min(25.0, revenue.value / 5000.0)
    if margin.is_available and margin.value is not None:
        score += min(15.0, margin.value * 100.0 / 3.0)
    if roe.is_available and roe.value is not None:
        score += min(10.0, max(0.0, roe.value * 10.0))

    return CompetitiveSummary(
        score=min(100.0, round(score, 2)),
        summary=(
            "Die Wettbewerbsposition wird aus den gemeldeten Größen und Margen in der "
            "letzten Periode beschrieben, ohne eine relative Rangfolge zu behaupten."
        ),
    )
