from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.decision import (
    DecisionCategory,
    DecisionChange,
    DecisionConfidence,
    EvidenceItem,
    InvestmentDecisionBrief,
)
from app.domain.facts import Confidence
from app.domain.financials import Metric
from app.services.analysis import analyse_company
from app.services.decision_engine import (
    build_decision_input,
    evaluate_decision,
    validate_evidence,
)
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


def analysis(*, omit: set[Metric] | None = None):
    return analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(omit=omit),
        market_data=ConfigurableFakeMarketData(),
    )


def test_decision_domain_accepts_only_neutral_categories() -> None:
    assert DecisionCategory.WATCH.value == "WATCH"
    with pytest.raises(ValidationError):
        InvestmentDecisionBrief(
            ticker="EXMP",
            company_name="Example",
            generated_at=datetime.now(UTC),
            decision="BUY",
            confidence=DecisionConfidence.MEDIUM,
            confidence_reason="test",
            summary="test",
            why="test",
            valuation_summary={},
            beginner_explanation={},
        )


def test_evidence_requires_a_statement_and_supports_sources() -> None:
    evidence = EvidenceItem(
        evidence_id="revenue",
        category="fact",
        statement="Revenue is available.",
        supporting_fact_ids=["revenue"],
        confidence=Confidence.HIGH,
        importance=2,
    )
    assert evidence.supporting_fact_ids == ["revenue"]
    with pytest.raises(ValidationError):
        EvidenceItem(evidence_id="x", category="fact", statement="")


def test_evidence_validation_rejects_unknown_fact_or_missing_source() -> None:
    evidence = EvidenceItem(
        evidence_id="revenue",
        category="fact",
        statement="Revenue is available.",
        supporting_fact_ids=["missing"],
    )
    with pytest.raises(ValueError, match="unknown fact"):
        validate_evidence([evidence], {"revenue"})

    evidence = evidence.model_copy(update={"supporting_fact_ids": ["revenue"]})
    with pytest.raises(ValueError, match="source references"):
        validate_evidence([evidence], {"revenue"})


def test_complete_structured_analysis_gets_a_non_empty_decision() -> None:
    brief = evaluate_decision(build_decision_input(analysis(), analysis_run_id="run-1"))

    assert brief.decision is not DecisionCategory.INSUFFICIENT_DATA
    assert brief.confidence in set(DecisionConfidence)
    assert brief.analysis_run_id == "run-1"
    assert brief.evidence
    assert brief.beginner_explanation.key_terms["DCF"]
    assert brief.model_metadata["engine"] == "deterministic"


def test_missing_core_metrics_is_insufficient_data() -> None:
    data = build_decision_input(
        analysis(omit={Metric.REVENUE, Metric.NET_INCOME, Metric.FREE_CASH_FLOW})
    )

    brief = evaluate_decision(data)

    assert brief.decision is DecisionCategory.INSUFFICIENT_DATA
    assert brief.confidence is DecisionConfidence.LOW
    assert brief.key_uncertainties


def test_missing_sources_is_insufficient_data() -> None:
    data = build_decision_input(analysis())
    data = data.model_copy(update={"source_count": 0})

    brief = evaluate_decision(data)

    assert brief.decision is DecisionCategory.INSUFFICIENT_DATA


def test_historical_comparison_reports_changes_without_markdown() -> None:
    previous = build_decision_input(analysis(), analysis_run_id="previous")
    current = build_decision_input(analysis(), analysis_run_id="current", previous=previous)

    brief = evaluate_decision(current)

    assert brief.decision_change is not None
    assert brief.decision_change.previous_decision in set(DecisionCategory)
    assert brief.decision_change.current_decision is brief.decision
    assert brief.decision_change.key_changes
    assert "markdown" not in brief.model_dump_json().lower()


def test_historical_comparison_detects_thesis_and_risk_changes() -> None:
    previous = build_decision_input(analysis(), analysis_run_id="previous")
    current = build_decision_input(
        analysis(), analysis_run_id="current", previous=previous
    ).model_copy(
        update={
            "thesis": "Changed thesis",
            "risk_signals": [{"name": "new risk", "score": 80.0, "summary": "risk"}],
        }
    )

    change = evaluate_decision(current).decision_change

    assert change is not None
    assert change.thesis_change == "verändert"
    assert change.risk_change == "verändert"


def test_decision_change_model_is_structured() -> None:
    change = DecisionChange(
        current_decision=DecisionCategory.WATCH,
        current_confidence=DecisionConfidence.MEDIUM,
        important_change="No material change",
    )
    assert change.decision_changed is False
