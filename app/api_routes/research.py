"""Structured research endpoints for the future frontend."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.repositories.analysis_store import SqlAnalysisStore
from app.services.research_view import ResearchViewService


class StockResponse(BaseModel):
    run_id: str
    ticker: str
    company_name: str
    generated_at: str
    currency: str | None
    assumptions: dict[str, Any]
    valuation: dict[str, Any]
    market: dict[str, Any] | None
    warnings: list[str]
    risk_signals: list[dict[str, Any]]
    competitive: dict[str, Any] | None
    scenarios: list[dict[str, Any]]
    thesis: str | None
    financials: list[dict[str, Any]]
    sources: list[str]
    report_available: bool


def build_research_router(store: SqlAnalysisStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/stocks", tags=["research"])
    service = ResearchViewService(store)

    @router.get("/{ticker}", response_model=StockResponse)
    def stock(ticker: str) -> dict[str, Any]:
        result = service.latest_stock(ticker)
        if result is None:
            raise HTTPException(status_code=404, detail="no saved analysis for ticker")
        result["generated_at"] = result["generated_at"].isoformat()
        return result

    @router.get("/{ticker}/financials")
    def financials(ticker: str) -> list[dict[str, Any]]:
        result = service.latest_stock(ticker)
        if result is None:
            raise HTTPException(status_code=404, detail="no saved analysis for ticker")
        return cast(list[dict[str, Any]], result["financials"])

    @router.get("/{ticker}/valuation")
    def valuation(ticker: str) -> dict[str, Any]:
        result = service.latest_stock(ticker)
        if result is None:
            raise HTTPException(status_code=404, detail="no saved analysis for ticker")
        return {
            "ticker": result["ticker"],
            "valuation": result["valuation"],
            "market": result["market"],
            "assumptions": result["assumptions"],
        }

    @router.get("/{ticker}/reports")
    def reports(ticker: str) -> dict[str, Any]:
        result = service.latest_stock(ticker)
        if result is None:
            raise HTTPException(status_code=404, detail="no saved analysis for ticker")
        report = service.report(result["run_id"])
        return report or {"run_id": result["run_id"], "markdown": None}

    return router
