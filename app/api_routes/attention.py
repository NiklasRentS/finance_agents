"""Structured decision history and watchlist attention endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.domain.decision import DecisionCategory, DecisionConfidence
from app.domain.decision_history import WatchlistAttentionResponse
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.decision_history import DecisionHistoryService


class DecisionHistoryResponse(BaseModel):
    ticker: str
    current_run_id: str
    current_generated_at: str
    current_decision: DecisionCategory
    current_confidence: DecisionConfidence
    previous_run_id: str | None
    previous_generated_at: str | None
    previous_decision: DecisionCategory | None
    previous_confidence: DecisionConfidence | None
    decision_changed: bool
    key_changes: list[str]
    valuation_change: str
    risk_change: str
    thesis_change: str
    scenario_change: str
    important_change: str
    evidence: list[dict[str, object]]


def build_attention_router(store: SqlAnalysisStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["decision-history"])
    service = DecisionHistoryService(store)

    @router.get("/stocks/{ticker}/changes", response_model=DecisionHistoryResponse)
    def changes(ticker: str) -> dict[str, object]:
        history = service.compare_latest(ticker)
        if history is None:
            raise HTTPException(status_code=404, detail="no decision history for ticker")
        return history.model_dump(mode="json")

    @router.get("/watchlist/attention", response_model=WatchlistAttentionResponse)
    def attention(limit: int = Query(default=3, ge=1, le=20)) -> WatchlistAttentionResponse:
        return service.watchlist_attention(limit=limit)

    return router
