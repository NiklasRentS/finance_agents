"""Structured decision history and watchlist attention endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.repositories.analysis_store import SqlAnalysisStore
from app.services.decision_history import DecisionHistoryService


def build_attention_router(store: SqlAnalysisStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["decision-history"])
    service = DecisionHistoryService(store)

    @router.get("/stocks/{ticker}/changes")
    def changes(ticker: str) -> dict[str, object]:
        history = service.compare_latest(ticker)
        if history is None:
            raise HTTPException(status_code=404, detail="no decision history for ticker")
        return history.model_dump(mode="json")

    @router.get("/watchlist/attention")
    def attention(limit: int = Query(default=3, ge=1, le=20)) -> dict[str, object]:
        return service.watchlist_attention(limit=limit).model_dump(mode="json")

    return router
