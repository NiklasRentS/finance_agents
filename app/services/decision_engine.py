"""Deterministic decision framework over existing structured analysis data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.agents.earnings import build_earnings_delta
from app.agents.risk import build_risk_signals
from app.agents.scenarios import build_scenario_outcomes, build_thesis_statement
from app.domain.decision import (
    BeginnerExplanation,
    DecisionCategory,
    DecisionChange,
    DecisionConfidence,
    DecisionInput,
    EvidenceItem,
    InvestmentDecisionBrief,
    ValuationSummary,
)
from app.domain.facts import Confidence
from app.domain.financials import Metric
from app.services.analysis import CompanyAnalysis
from app.services.valuation import Multiples

_CORE_METRICS = (Metric.REVENUE, Metric.NET_INCOME, Metric.FREE_CASH_FLOW)
_TERM_DEFINITIONS = {
    "P/E": "Wie viel bezahlen Anleger aktuell für eine Einheit Jahresgewinn?",
    "DCF": "Eine Modellrechnung, die erwartete Cashflows auf einen heutigen Wert zurückrechnet.",
    "Free Cash Flow": "Wie viel Geld nach den notwendigen Investitionen tatsächlich übrig bleibt.",
    "Margin": "Welcher Anteil des Umsatzes nach bestimmten Kosten übrig bleibt.",
    "ROIC": "Wie effizient das Unternehmen das eingesetzte Kapital nutzt.",
    "Debt": "Verbindlichkeiten, die das Unternehmen gegenüber anderen hat.",
}


def build_decision_input(
    analysis: CompanyAnalysis,
    *,
    analysis_run_id: str | None = None,
    previous: DecisionInput | None = None,
) -> DecisionInput:
    """Adapt an existing CompanyAnalysis without recalculating financial values."""
    latest = analysis.latest
    latest_values: dict[str, Any] = {}
    unavailable: list[str] = []
    low_confidence = 0
    if latest is not None:
        for metric in Metric:
            fact = latest.get(metric)
            if fact.is_available:
                latest_values[metric.value] = fact
                if fact.confidence in {Confidence.LOW, Confidence.UNKNOWN}:
                    low_confidence += 1
            elif metric in _CORE_METRICS:
                unavailable.append(metric.value)
    else:
        unavailable.extend(metric.value for metric in _CORE_METRICS)

    trend_values = {
        metric.value: trend.cagr
        for metric, trend in analysis.trends.items()
        if trend.cagr is not None and trend.cagr.is_available
    }
    trend_directions = {
        metric.value: trend.direction.value for metric, trend in analysis.trends.items()
    }
    valuation = ValuationSummary(
        dcf_available=analysis.valuation.is_available,
        fair_value=analysis.valuation.value_per_share,
        current_price=None if analysis.quote is None else analysis.quote.price,
        multiples=_multiples(analysis.multiples),
        interpretation="",
    )
    earnings = [
        {
            "metric": delta.metric.value,
            "current": delta.current,
            "previous": delta.previous,
            "delta": delta.delta,
            "pct_change": delta.pct_change,
        }
        for delta in build_earnings_delta(analysis)
    ]
    return DecisionInput(
        ticker=analysis.ticker,
        company_name=analysis.company.name,
        generated_at=analysis.generated_at,
        analysis_run_id=analysis_run_id,
        latest_values=latest_values,
        trend_values=trend_values,
        trend_directions=trend_directions,
        valuation=valuation,
        warnings=list(analysis.warnings),
        risk_signals=[signal.__dict__ for signal in build_risk_signals(analysis)],
        scenarios=[scenario.__dict__ for scenario in build_scenario_outcomes(analysis)],
        thesis=build_thesis_statement(analysis),
        catalysts=[],
        earnings_changes=earnings,
        source_count=_source_count(latest_values, trend_values, valuation),
        low_confidence_fact_count=low_confidence,
        unavailable_core_metrics=unavailable,
        previous=previous,
    )


def evaluate_decision(data: DecisionInput) -> InvestmentDecisionBrief:
    evidence = _evidence(data)
    validate_evidence(
        evidence,
        set(data.latest_values) | {"valuation.fair_value"},
    )
    confidence, confidence_reason = _confidence(data)
    decision = _decision(data, confidence)
    positive = _positive_factors(data)
    negative = _negative_factors(data)
    risks = [
        str(signal.get("summary", ""))
        for signal in data.risk_signals
        if signal.get("summary")
    ]
    uncertainties = _uncertainties(data)
    valuation = data.valuation.model_copy(
        update={
            "interpretation": _valuation_interpretation(data),
            "evidence_ids": _valuation_evidence_ids(data),
        }
    )
    change = _compare_with_previous(data, decision, confidence, evidence)
    return InvestmentDecisionBrief(
        ticker=data.ticker,
        company_name=data.company_name,
        generated_at=datetime.now(UTC),
        decision=decision,
        confidence=confidence,
        confidence_reason=confidence_reason,
        summary=_summary(decision, data),
        why=_why(decision, data),
        investment_thesis=data.thesis,
        positive_factors=positive,
        negative_factors=negative,
        key_risks=risks,
        valuation_summary=valuation,
        key_uncertainties=uncertainties,
        thesis_improvers=["Bessere operative Entwicklung mit belegtem Cashflow"],
        thesis_deteriorators=["Schwächere Margen oder zunehmende Verschuldung"],
        monitoring_points=_monitoring_points(data),
        beginner_explanation=_beginner_explanation(data, valuation),
        evidence=evidence,
        decision_change=change,
        analysis_run_id=data.analysis_run_id,
        model_metadata={"engine": "deterministic", "version": "1"},
    )


def validate_evidence(
    evidence: list[EvidenceItem], available_fact_ids: set[str]
) -> None:
    """Reject decision evidence that cannot be traced to supplied facts/sources."""
    for item in evidence:
        if not item.supporting_fact_ids:
            raise ValueError(f"evidence {item.evidence_id} has no supporting facts")
        if not set(item.supporting_fact_ids).issubset(available_fact_ids):
            raise ValueError(f"evidence {item.evidence_id} references an unknown fact")
        if not item.source_refs:
            raise ValueError(f"evidence {item.evidence_id} has no source references")


def _multiples(multiples: Multiples | None) -> dict[str, Any]:
    if multiples is None:
        return {}
    return {
        name: value
        for name, value in {
            "price_earnings": multiples.price_earnings,
            "price_book": multiples.price_book,
            "ev_ebitda": multiples.ev_ebitda,
        }.items()
        if value.is_available
    }


def _source_count(
    latest_values: dict[str, Any],
    trend_values: dict[str, Any],
    valuation: ValuationSummary,
) -> int:
    sources: set[str] = set()
    for group in (latest_values, trend_values, valuation.multiples):
        for value in group.values():
            if hasattr(value, "sources"):
                sources.update(source.citation() for source in value.sources)
    for value in (valuation.fair_value, valuation.current_price):
        if value is not None:
            sources.update(source.citation() for source in value.sources)
    return len(sources)


def _evidence(data: DecisionInput) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for metric_name in (Metric.REVENUE.value, Metric.FREE_CASH_FLOW.value, Metric.ROIC.value):
        fact = data.latest_values.get(metric_name)
        if fact is None:
            continue
        items.append(
            _fact_evidence(
                metric_name,
                fact,
                f"{metric_name} ist für die aktuelle Periode belegt.",
            )
        )
    if data.valuation.fair_value is not None and data.valuation.fair_value.is_available:
        items.append(
            _fact_evidence(
                "valuation.fair_value",
                data.valuation.fair_value,
                "Ein modellierter Fair Value ist unter den vorhandenen DCF-Annahmen verfügbar.",
            )
        )
    return items


def _fact_evidence(evidence_id: str, fact: Any, statement: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        category="fact",
        statement=statement,
        supporting_fact_ids=[evidence_id],
        source_refs=list(fact.sources),
        confidence=fact.confidence,
        importance=2,
    )


def _confidence(data: DecisionInput) -> tuple[DecisionConfidence, str]:
    if data.source_count == 0 or data.unavailable_core_metrics:
        return DecisionConfidence.LOW, "Zentrale Finanzdaten oder Quellen fehlen."
    if data.low_confidence_fact_count > 0 or data.warnings or not data.valuation.dcf_available:
        return DecisionConfidence.MEDIUM, (
            "Die Einschätzung ist grundsätzlich belegt, enthält aber relevante "
            "Unsicherheiten."
        )
    return DecisionConfidence.HIGH, "Aktuelle Kernkennzahlen und Quellen sind konsistent verfügbar."


def _decision(data: DecisionInput, confidence: DecisionConfidence) -> DecisionCategory:
    if data.unavailable_core_metrics or data.source_count == 0:
        return DecisionCategory.INSUFFICIENT_DATA
    if confidence is DecisionConfidence.LOW:
        return DecisionCategory.INSUFFICIENT_DATA
    if data.warnings or not data.valuation.dcf_available:
        return DecisionCategory.REVIEW_THESIS
    fair = data.valuation.fair_value.value if data.valuation.fair_value else None
    price = data.valuation.current_price.value if data.valuation.current_price else None
    if fair is None or price is None or price <= 0:
        return DecisionCategory.WATCH
    if fair > price * 1.15 and not data.risk_signals:
        return DecisionCategory.ATTRACTIVE
    if fair < price * 0.95 or len(data.risk_signals) >= 2:
        return DecisionCategory.CAUTION
    return DecisionCategory.WATCH


def _positive_factors(data: DecisionInput) -> list[str]:
    factors: list[str] = []
    for metric in (Metric.REVENUE.value, Metric.FREE_CASH_FLOW.value, Metric.ROIC.value):
        if metric in data.latest_values:
            factors.append(f"{metric} ist in der aktuellen Analyse belegt.")
    return factors


def _negative_factors(data: DecisionInput) -> list[str]:
    factors = list(data.warnings)
    if data.valuation.interpretation:
        factors.append(data.valuation.interpretation)
    return factors


def _uncertainties(data: DecisionInput) -> list[str]:
    uncertainties = list(data.warnings)
    if data.unavailable_core_metrics:
        uncertainties.append(
            "Zentrale Kennzahlen fehlen: " + ", ".join(data.unavailable_core_metrics)
        )
    if not data.valuation.dcf_available:
        uncertainties.append("Kein belastbarer DCF-Wert verfügbar.")
    if data.low_confidence_fact_count:
        uncertainties.append(
            "Mindestens ein verwendeter Fakt hat niedrige oder unbekannte Confidence."
        )
    return uncertainties


def _valuation_interpretation(data: DecisionInput) -> str:
    fair = data.valuation.fair_value.value if data.valuation.fair_value else None
    price = data.valuation.current_price.value if data.valuation.current_price else None
    if fair is None or price is None:
        return (
            "Bewertung kann mangels vollständiger Vergleichsdaten nicht belastbar "
            "eingeordnet werden."
        )
    if fair > price:
        return (
            "Der modellierte Fair Value liegt über dem aktuellen Kurs; die Aussage "
            "bleibt annahmenabhängig."
        )
    return (
        "Der modellierte Fair Value liegt nicht über dem aktuellen Kurs; die Bewertung "
        "verdient besondere Prüfung."
    )


def _valuation_evidence_ids(data: DecisionInput) -> list[str]:
    ids = []
    if data.valuation.fair_value is not None and data.valuation.fair_value.is_available:
        ids.append("valuation.fair_value")
    if data.valuation.current_price is not None and data.valuation.current_price.is_available:
        ids.append("market.price")
    return ids


def _monitoring_points(data: DecisionInput) -> list[str]:
    points = ["Umsatz- und Margentrend der nächsten Berichtsperiode"]
    if data.valuation.dcf_available:
        points.append("Entwicklung des Free Cash Flow gegenüber den DCF-Annahmen")
    if data.risk_signals:
        points.append("Veränderung der vorhandenen Risiko-Signale")
    return points


def _beginner_explanation(data: DecisionInput, valuation: ValuationSummary) -> BeginnerExplanation:
    return BeginnerExplanation(
        explanation=(
            f"Die Analyse ordnet {data.company_name} anhand belegter "
            "Geschäftszahlen, Risiken und Bewertungsannahmen ein."
        ),
        why_it_matters=(
            "Die Kategorie beschreibt die Qualität der aktuellen Evidenz, nicht "
            "die sichere Entwicklung des Aktienkurses."
        ),
        key_terms=dict(_TERM_DEFINITIONS),
    )


def _summary(decision: DecisionCategory, data: DecisionInput) -> str:
    return (
        f"Die aktuelle Datenlage führt zu {decision.value}; die Kategorie ist eine "
        "strukturierte Research-Einordnung und keine Handlungsaufforderung."
    )


def _why(decision: DecisionCategory, data: DecisionInput) -> str:
    if decision is DecisionCategory.INSUFFICIENT_DATA:
        return "Zentrale Daten oder Quellen fehlen für eine belastbare Entscheidung."
    if decision is DecisionCategory.CAUTION:
        return "Bewertung oder Risiko-Signale sprechen für eine vorsichtige Einordnung."
    if decision is DecisionCategory.REVIEW_THESIS:
        return "Die Analyse enthält relevante Warnungen oder Bewertungsunsicherheit."
    return (
        "Die Kategorie folgt aus den vorhandenen strukturierten Fundamentaldaten "
        "und Bewertungsinputs."
    )


def _compare_with_previous(
    data: DecisionInput,
    current: DecisionCategory,
    confidence: DecisionConfidence,
    evidence: list[EvidenceItem],
) -> DecisionChange | None:
    previous = data.previous
    if previous is None:
        return None
    previous_brief = evaluate_decision(previous) if previous.previous is None else None
    previous_decision = previous_brief.decision if previous_brief else DecisionCategory.WATCH
    previous_confidence = previous_brief.confidence if previous_brief else DecisionConfidence.MEDIUM
    changes: list[str] = []
    if (
        data.valuation.fair_value
        and previous.valuation.fair_value
        and data.valuation.fair_value.value != previous.valuation.fair_value.value
    ):
        changes.append("Der modellierte Fair Value hat sich verändert.")
    if data.thesis != previous.thesis:
        changes.append("Die strukturierte Investmentthese hat sich verändert.")
    if data.risk_signals != previous.risk_signals:
        changes.append("Die Risiko-Signale haben sich verändert.")
    if not changes:
        changes.append("Keine wesentliche strukturierte Veränderung erkannt.")
    return DecisionChange(
        previous_decision=previous_decision,
        current_decision=current,
        previous_confidence=previous_confidence,
        current_confidence=confidence,
        decision_changed=previous_decision != current,
        key_changes=changes,
        thesis_change="verändert" if data.thesis != previous.thesis else "unverändert",
        valuation_change="verändert" if data.valuation != previous.valuation else "unverändert",
        risk_change="verändert" if data.risk_signals != previous.risk_signals else "unverändert",
        scenario_change="verändert" if data.scenarios != previous.scenarios else "unverändert",
        important_change=changes[0],
        evidence=evidence,
    )
