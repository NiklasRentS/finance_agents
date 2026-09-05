"""Structured historical decision comparison and watchlist attention models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.decision import DecisionCategory, DecisionConfidence, EvidenceItem


class DecisionHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    current_run_id: str
    current_generated_at: datetime
    current_decision: DecisionCategory
    current_confidence: DecisionConfidence
    previous_run_id: str | None = None
    previous_generated_at: datetime | None = None
    previous_decision: DecisionCategory | None = None
    previous_confidence: DecisionConfidence | None = None
    decision_changed: bool = False
    key_changes: list[str] = Field(default_factory=list)
    valuation_change: str = "unavailable"
    risk_change: str = "unavailable"
    thesis_change: str = "unavailable"
    scenario_change: str = "unavailable"
    important_change: str = "No previous decision brief available."
    evidence: list[EvidenceItem] = Field(default_factory=list)


class WatchlistAttentionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    company_name: str
    priority: int = Field(ge=0)
    reason: str
    current_decision: DecisionCategory | None = None
    previous_decision: DecisionCategory | None = None
    latest_run_id: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class WatchlistAttentionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[WatchlistAttentionItem] = Field(default_factory=list)
    message: str | None = None
