"""Structured, LLM-free investment decision domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.facts import Confidence, SourceRef
from app.domain.financials import NumericFact


class DecisionCategory(StrEnum):
    ATTRACTIVE = "ATTRACTIVE"
    WATCH = "WATCH"
    CAUTION = "CAUTION"
    REVIEW_THESIS = "REVIEW_THESIS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DecisionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceItem(BaseModel):
    """A decision statement with links back to existing facts and sources."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    supporting_fact_ids: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    importance: int = Field(default=1, ge=1, le=3)


class DecisionChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    previous_decision: DecisionCategory | None = None
    current_decision: DecisionCategory
    previous_confidence: DecisionConfidence | None = None
    current_confidence: DecisionConfidence
    decision_changed: bool = False
    key_changes: list[str] = Field(default_factory=list)
    thesis_change: str | None = None
    valuation_change: str | None = None
    risk_change: str | None = None
    scenario_change: str | None = None
    important_change: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class BeginnerExplanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    explanation: str = ""
    why_it_matters: str = ""
    key_terms: dict[str, str] = Field(default_factory=dict)


class ValuationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    dcf_available: bool = False
    fair_value: NumericFact | None = None
    current_price: NumericFact | None = None
    multiples: dict[str, NumericFact] = Field(default_factory=dict)
    interpretation: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class DecisionInput(BaseModel):
    """Structured input assembled from one existing CompanyAnalysis."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    company_name: str
    generated_at: datetime
    analysis_run_id: str | None = None
    latest_values: dict[str, NumericFact] = Field(default_factory=dict)
    trend_values: dict[str, NumericFact] = Field(default_factory=dict)
    trend_directions: dict[str, str] = Field(default_factory=dict)
    valuation: ValuationSummary
    warnings: list[str] = Field(default_factory=list)
    risk_signals: list[dict[str, Any]] = Field(default_factory=list)
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    thesis: str | None = None
    catalysts: list[dict[str, Any]] = Field(default_factory=list)
    earnings_changes: list[dict[str, Any]] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    low_confidence_fact_count: int = Field(default=0, ge=0)
    unavailable_core_metrics: list[str] = Field(default_factory=list)
    previous: DecisionInput | None = None


class InvestmentDecisionBrief(BaseModel):
    """Frontend- and LLM-ready decision framework without Markdown coupling."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    company_name: str
    generated_at: datetime
    decision: DecisionCategory
    confidence: DecisionConfidence
    confidence_reason: str
    summary: str
    why: str
    investment_thesis: str | None = None
    positive_factors: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    valuation_summary: ValuationSummary
    key_uncertainties: list[str] = Field(default_factory=list)
    thesis_improvers: list[str] = Field(default_factory=list)
    thesis_deteriorators: list[str] = Field(default_factory=list)
    monitoring_points: list[str] = Field(default_factory=list)
    beginner_explanation: BeginnerExplanation
    evidence: list[EvidenceItem] = Field(default_factory=list)
    decision_change: DecisionChange | None = None
    analysis_run_id: str | None = None
    model_metadata: dict[str, Any] = Field(default_factory=dict)


class InvestmentDecisionExplanation(BaseModel):
    """Validated LLM explanation layered over an authoritative decision brief."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    company_name: str
    decision: DecisionCategory
    confidence: DecisionConfidence
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    why_this_matters: str = Field(min_length=1)
    positive_factors: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    valuation_explanation: str = ""
    uncertainty: str = ""
    what_to_watch: list[str] = Field(default_factory=list)
    beginner_explanation: BeginnerExplanation
    evidence: list[EvidenceItem] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
