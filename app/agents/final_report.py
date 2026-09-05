from __future__ import annotations

from app.agents.competitive import build_competitive_summary
from app.agents.earnings import build_earnings_delta
from app.agents.risk import build_risk_signals
from app.agents.scenarios import build_scenario_outcomes, build_thesis_statement
from app.domain.financials import Metric
from app.services.analysis import CompanyAnalysis


def build_final_research_report(analysis: CompanyAnalysis) -> str:
    latest = analysis.latest
    if latest is None:
        return "# Finaler Forschungsbericht\n\nKeine Daten für die Analyse vorhanden."

    deltas = build_earnings_delta(analysis)
    risk_signals = build_risk_signals(analysis)
    competitive = build_competitive_summary(analysis)
    scenarios = build_scenario_outcomes(analysis)
    thesis = build_thesis_statement(analysis)

    metric_lines = [
        f"- {metric.value}: {latest.get(metric).display()}"
        for metric in (
            Metric.REVENUE,
            Metric.GROSS_MARGIN,
            Metric.OPERATING_MARGIN,
            Metric.NET_INCOME,
            Metric.FREE_CASH_FLOW,
            Metric.ROE,
            Metric.ROIC,
        )
        if latest.get(metric).is_available
    ]

    delta_lines = [
        f"- {delta.metric.value}: Delta {delta.delta:,.2f}, Wachstumsrate {delta.pct_change:.2%}."
        for delta in deltas
    ] or ["- Keine Delta-Vergleiche mit vorheriger Periode verfügbar."]

    risk_lines = [
        f"- {signal.name}: Score {signal.score:.2f} — {signal.summary}"
        for signal in risk_signals
    ] or ["- Keine Risikosignale aus den verfügbaren Daten abgeleitet."]

    scenario_lines = [
        f"- {scenario.name} ({scenario.probability:.0%}): {scenario.narrative}"
        for scenario in scenarios
    ]

    lines = [
        "# Finaler Forschungsbericht",
        "",
        "## 1. Unternehmensprofil",
        "",
        f"- Unternehmen: {analysis.company.name}",
        f"- Ticker: {analysis.ticker}",
        f"- Berichtsperiode: {latest.period.label}",
        f"- Währung: {analysis.history.currency or 'unbekannt'}",
        "",
        "## 2. Kennzahlen",
        "",
        *metric_lines,
        "",
        "## 3. Ergebnisse",
        "",
        *delta_lines,
        "",
        "## 4. Risiken",
        "",
        *risk_lines,
        "",
        "## 5. Wettbewerbsposition",
        "",
        f"- Wettbewerbswert: {competitive.score:.2f}",
        f"- Beschreibung: {competitive.summary}",
        "",
        "## 6. Szenarien",
        "",
        *scenario_lines,
        "",
        "## 7. These",
        "",
        thesis,
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"
