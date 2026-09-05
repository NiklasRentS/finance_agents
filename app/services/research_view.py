"""Structured views over persisted research runs for API consumers."""

from __future__ import annotations

import uuid
from typing import Any

from app.repositories.analysis_store import SqlAnalysisStore


class ResearchViewService:
    def __init__(self, store: SqlAnalysisStore) -> None:
        self._store = store

    def latest_stock(self, ticker: str) -> dict[str, Any] | None:
        run = self._store.load_latest_run(ticker)
        if run is None:
            return None
        history = self._store.load_history(run.id)
        if history is None:
            return None
        sources = {
            source.citation()
            for snapshot in history.sorted_snapshots()
            for fact in snapshot.values.values()
            for source in fact.sources
        }
        return {
            "run_id": str(run.id),
            "ticker": run.ticker,
            "company_name": run.company_name,
            "generated_at": run.generated_at,
            "currency": run.currency,
            "assumptions": run.assumptions,
            "valuation": run.valuation,
            "market": run.market,
            "warnings": run.warnings,
            "risk_signals": run.risk_signals or [],
            "competitive": run.competitive,
            "scenarios": run.scenarios or [],
            "thesis": run.thesis,
            "catalysts": run.catalysts or [],
            "financials": [
                {
                    "period": snapshot.period.model_dump(mode="json"),
                    "values": {
                        metric.value: fact.model_dump(mode="json")
                        for metric, fact in snapshot.values.items()
                    },
                }
                for snapshot in history.sorted_snapshots()
            ],
            "sources": sorted(sources),
            "report_available": run.report_markdown is not None,
        }

    def report(self, run_id: str) -> dict[str, Any] | None:
        try:
            identifier = uuid.UUID(run_id)
        except ValueError:
            return None
        run = self._store.load_run_document(identifier)
        if run is None:
            return None
        return {"run_id": str(run.id), "markdown": run.report_markdown}
