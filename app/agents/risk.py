from __future__ import annotations

from dataclasses import dataclass

from app.domain.financials import Metric
from app.services.analysis import CompanyAnalysis


@dataclass(frozen=True)
class RiskSignal:
    name: str
    score: float
    summary: str


def build_risk_signals(analysis: CompanyAnalysis) -> list[RiskSignal]:
    latest = analysis.latest
    if latest is None:
        return []
    debt = latest.get(Metric.TOTAL_DEBT)
    margin = latest.get(Metric.GROSS_MARGIN)
    signals: list[RiskSignal] = []

    if debt.is_available and debt.value is not None:
        score = min(100.0, max(0.0, debt.value / max(1.0, latest.get(Metric.TOTAL_ASSETS).value or 1.0) * 100.0))
        signals.append(
            RiskSignal(
                name="Schuldenlast",
                score=round(score, 2),
                summary=(
                    "Die Verschuldung steht in Relation zur Bilanzsumme, ohne die relative "
                    "Bonität zu beurteilen."
                ),
            )
        )

    if margin.is_available and margin.value is not None:
        score = max(0.0, min(100.0, 100.0 - (margin.value * 100.0)))
        signals.append(
            RiskSignal(
                name="Margenvolatilität",
                score=round(score, 2),
                summary="Die Bruttomarge zeigt die Bandbreite der Ertragsstärke, ohne eine Bewertung vorzunehmen.",
            )
        )

    return signals
