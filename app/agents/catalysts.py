"""Fact-grounded positive research observations."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.financials import Metric
from app.services.analysis import CompanyAnalysis


@dataclass(frozen=True)
class CatalystPoint:
    name: str
    summary: str


def build_catalyst_points(analysis: CompanyAnalysis) -> list[CatalystPoint]:
    latest = analysis.latest
    if latest is None:
        return []
    points: list[CatalystPoint] = []
    revenue = latest.get(Metric.REVENUE)
    fcf = latest.get(Metric.FREE_CASH_FLOW)
    margin = latest.get(Metric.GROSS_MARGIN)
    if revenue.is_available:
        points.append(
            CatalystPoint("Umsatzbasis", "Eine aktuelle gemeldete Umsatzbasis ist vorhanden.")
        )
    if fcf.is_available:
        points.append(
            CatalystPoint("Cashflow", "Free Cash Flow ist für die aktuelle Periode belegt.")
        )
    if margin.is_available:
        points.append(
            CatalystPoint("Marge", "Eine aktuelle Bruttomarge ist für die Beobachtung verfügbar.")
        )
    return points
