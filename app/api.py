"""HTTP API for saved research runs and watchlists."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.api_routes.portfolio import build_portfolio_router
from app.config.settings import get_settings
from app.repositories.analysis_store import SqlAnalysisStore
from app.repositories.broker_store import SqlBrokerStore


class WatchlistItemCreate(BaseModel):
    ticker: str = Field(..., min_length=1)
    company_name: str = Field(..., min_length=1)
    notes: str | None = None


class RunListItem(BaseModel):
    id: str
    ticker: str
    company_name: str
    generated_at: str
    currency: str | None = None
    period_label: str | None = None
    value_per_share: float | None = None


class MetricDelta(BaseModel):
    metric: str
    base_value: float | None = None
    other_value: float | None = None
    delta: float | None = None
    percent_change: float | None = None


class DiffResponse(BaseModel):
    base_run_id: str
    other_run_id: str
    metrics: list[MetricDelta]


class HistoryResponse(BaseModel):
    run_id: str
    currency: str | None = None
    snapshots: list[dict[str, Any]]


class AlertResponse(BaseModel):
    ticker: str
    threshold: float
    alerts: list[dict[str, Any]]


def _compare_histories(history_a: Any, history_b: Any) -> list[MetricDelta]:
    metric_names: set[str] = set()
    for snapshot in history_a.sorted_snapshots():
        metric_names.update(metric.value for metric in snapshot.values)
    for snapshot in history_b.sorted_snapshots():
        metric_names.update(metric.value for metric in snapshot.values)

    results: list[MetricDelta] = []
    for metric_name in sorted(metric_names):
        base_value = None
        other_value = None
        for snapshot in history_a.sorted_snapshots():
            fact = snapshot.values.get(metric_name)
            if fact is not None and fact.value is not None:
                base_value = float(fact.value)
                break
        for snapshot in history_b.sorted_snapshots():
            fact = snapshot.values.get(metric_name)
            if fact is not None and fact.value is not None:
                other_value = float(fact.value)
                break
        if base_value is None and other_value is None:
            continue

        delta = None if base_value is None or other_value is None else other_value - base_value
        percent_change = None
        if delta is not None and base_value not in (None, 0):
            percent_change = delta / base_value

        results.append(
            MetricDelta(
                metric=metric_name,
                base_value=base_value,
                other_value=other_value,
                delta=delta,
                percent_change=percent_change,
            )
        )
    return results


def create_app(
    *, store: SqlAnalysisStore | None = None, broker_store: SqlBrokerStore | None = None
) -> FastAPI:
    """Create the application instance."""
    app = FastAPI(title="Finance Agents API", version="0.1.0")
    active_store = store or SqlAnalysisStore.from_settings(get_settings())
    active_broker_store = broker_store or SqlBrokerStore.from_settings(get_settings())
    app.include_router(build_portfolio_router(active_broker_store))

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/runs", response_model=list[RunListItem])
    def list_runs() -> list[dict[str, Any]]:
        return [
            {
                "id": str(item.id),
                "ticker": item.ticker,
                "company_name": item.company_name,
                "generated_at": item.generated_at.isoformat(),
                "currency": item.currency,
                "period_label": item.period_label,
                "value_per_share": item.value_per_share,
            }
            for item in active_store.list_runs(limit=50)
        ]

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            identifier = uuid.UUID(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid run id") from exc
        summaries = active_store.list_runs(limit=50)
        match = next((item for item in summaries if item.id == identifier), None)
        if match is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {
            "id": str(match.id),
            "ticker": match.ticker,
            "company_name": match.company_name,
            "generated_at": match.generated_at.isoformat(),
            "currency": match.currency,
            "period_label": match.period_label,
            "value_per_share": match.value_per_share,
        }

    @app.get("/api/v1/runs/{run_id}/diff", response_model=DiffResponse)
    def diff_run(
        run_id: str,
        other_run_id: str = Query(..., description="Identifier of the other comparison run"),
    ) -> DiffResponse:
        try:
            base_id = uuid.UUID(run_id)
            second_id = uuid.UUID(other_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid run id") from exc

        base_history = active_store.load_history(base_id)
        other_history = active_store.load_history(second_id)
        if base_history is None or other_history is None:
            raise HTTPException(status_code=404, detail="run not found")

        return DiffResponse(
            base_run_id=str(base_id),
            other_run_id=str(second_id),
            metrics=_compare_histories(base_history, other_history),
        )

    @app.get("/api/v1/runs/{run_id}/history", response_model=HistoryResponse)
    def run_history(run_id: str) -> HistoryResponse:
        try:
            identifier = uuid.UUID(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid run id") from exc
        history = active_store.load_history(identifier)
        if history is None:
            raise HTTPException(status_code=404, detail="run not found")
        return HistoryResponse(
            run_id=str(identifier),
            currency=history.currency,
            snapshots=[
                {
                    "period": snapshot.period.model_dump(mode="json"),
                    "values": {
                        metric.value: fact.model_dump(mode="json")
                        for metric, fact in snapshot.values.items()
                    },
                }
                for snapshot in history.sorted_snapshots()
            ],
        )

    @app.get("/api/v1/alerts", response_model=AlertResponse)
    def alerts(
        ticker: str = Query(..., min_length=1),
        threshold: float = Query(0.10, ge=0),
    ) -> AlertResponse:
        normalized_ticker = ticker.strip().upper()
        summaries = active_store.list_runs(ticker=normalized_ticker, limit=2)
        if len(summaries) < 2:
            return AlertResponse(ticker=normalized_ticker, threshold=threshold, alerts=[])
        newer, older = summaries[0], summaries[1]
        newer_history = active_store.load_history(newer.id)
        older_history = active_store.load_history(older.id)
        if newer_history is None or older_history is None:
            return AlertResponse(ticker=normalized_ticker, threshold=threshold, alerts=[])

        changed = [
            delta
            for delta in _compare_histories(older_history, newer_history)
            if delta.percent_change is not None
            and abs(delta.percent_change) >= threshold
        ]
        return AlertResponse(
            ticker=normalized_ticker,
            threshold=threshold,
            alerts=[
                {
                    "metric": delta.metric,
                    "base_value": delta.base_value,
                    "other_value": delta.other_value,
                    "delta": delta.delta,
                    "percent_change": delta.percent_change,
                    "base_run_id": str(older.id),
                    "other_run_id": str(newer.id),
                }
                for delta in changed
            ],
        )

    @app.get("/api/v1/watchlist")
    def list_watchlist() -> list[dict[str, str | None]]:
        return active_store.list_watchlist()

    @app.post("/api/v1/watchlist")
    def create_watchlist_item(payload: WatchlistItemCreate) -> dict[str, str | None]:
        try:
            return active_store.add_watchlist_item(
                ticker=payload.ticker,
                company_name=payload.company_name,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()