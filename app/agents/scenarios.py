from __future__ import annotations

from dataclasses import dataclass

from app.domain.financials import Metric
from app.services.analysis import CompanyAnalysis


@dataclass(frozen=True)
class ScenarioOutcome:
    name: str
    probability: float
    narrative: str


def build_scenario_outcomes(analysis: CompanyAnalysis) -> list[ScenarioOutcome]:
    latest = analysis.latest
    if latest is None:
        return []

    revenue = latest.get(Metric.REVENUE)
    margin = latest.get(Metric.GROSS_MARGIN)
    fcf = latest.get(Metric.FREE_CASH_FLOW)
    outcomes = [
        ScenarioOutcome(
            name="Basisfall",
            probability=0.6,
            narrative=(
                "Die aktuelle Periodenlage bleibt im Kern stabil, sofern Umsatz, Marge und "
                "Cashflow in den bisher beobachteten Bereichen bleiben."
            ),
        )
    ]

    if revenue.is_available and revenue.value is not None:
        outcomes.append(
            ScenarioOutcome(
                name="Aufschwung",
                probability=0.25,
                narrative=(
                    "Ein höherer Umsatz bei vergleichbarer Marge würde die Inanspruchnahme "
                    "von Liquidität und Wachstum aufzeigen."
                ),
            )
        )
    if margin.is_available and margin.value is not None and fcf.is_available:
        outcomes.append(
            ScenarioOutcome(
                name="Verlustrisiko",
                probability=0.15,
                narrative=(
                    "Eine merkliche Senkung der Marge oder des Free Cash Flow würde auf "
                    "eine stärkere Belastung hinweisen, ohne sie direkt zu bewerten."
                ),
            )
        )

    return outcomes


def build_thesis_statement(analysis: CompanyAnalysis) -> str:
    latest = analysis.latest
    if latest is None:
        return "Keine Daten für eine These vorhanden."
    revenue = latest.get(Metric.REVENUE)
    margin = latest.get(Metric.GROSS_MARGIN)
    if revenue.is_available and margin.is_available:
        return (
            "Die operative Grundlage besteht aus der gemeldeten Umsatzbasis und der "
            "aktuellen Marge; die These bleibt auf diese Faktengrundlage beschränkt."
        )
    return "Die These bleibt offen, weil zentrale Kennzahlen nicht gleichzeitig belegt sind."
