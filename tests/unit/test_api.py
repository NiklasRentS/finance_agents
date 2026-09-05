from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.analysis import analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


@pytest.fixture
def store() -> Iterator[SqlAnalysisStore]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store = SqlAnalysisStore(engine)
    store.create_schema()
    yield store
    store.close()
    engine.dispose()


def _analysis(ticker: str = "EXMP") -> object:
    return analyse_company(
        ticker,
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )


def test_runs_endpoint_lists_saved_runs(store: SqlAnalysisStore) -> None:
    first_id = store.save_run(_analysis("AAPL"))
    second_id = store.save_run(_analysis("MSFT"))

    client = TestClient(create_app(store=store))
    response = client.get("/api/v1/runs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [str(second_id), str(first_id)]
    assert payload[0]["ticker"] == "MSFT"


def test_diff_endpoint_returns_active_changes(store: SqlAnalysisStore) -> None:
    first_id = store.save_run(_analysis("AAPL"))
    second_id = store.save_run(_analysis("MSFT"))

    client = TestClient(create_app(store=store))
    response = client.get(f"/api/v1/runs/{first_id}/diff?other_run_id={second_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_run_id"] == str(first_id)
    assert payload["other_run_id"] == str(second_id)
    assert "metrics" in payload
    assert payload["metrics"]


def test_watchlist_supports_create_and_list(store: SqlAnalysisStore) -> None:
    client = TestClient(create_app(store=store))

    create_response = client.post(
        "/api/v1/watchlist",
        json={"ticker": "AAPL", "company_name": "Apple Inc.", "notes": "Core holding"},
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["company_name"] == "Apple Inc."

    list_response = client.get("/api/v1/watchlist")
    assert list_response.status_code == 200
    assert list_response.json()[0]["ticker"] == "AAPL"


def test_history_endpoint_returns_provenance_backed_snapshots(store: SqlAnalysisStore) -> None:
    run_id = store.save_run(_analysis("AAPL"))

    client = TestClient(create_app(store=store))
    response = client.get(f"/api/v1/runs/{run_id}/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == str(run_id)
    assert payload["snapshots"]
    assert payload["snapshots"][-1]["values"]["revenue"]["sources"]


def test_alerts_endpoint_reports_large_run_to_run_changes(store: SqlAnalysisStore) -> None:
    store.save_run(_analysis("AAPL"))
    store.save_run(_analysis("AAPL"))

    client = TestClient(create_app(store=store))
    response = client.get("/api/v1/alerts?ticker=AAPL&threshold=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["alerts"]
    assert {"metric", "percent_change", "base_run_id", "other_run_id"} <= set(
        payload["alerts"][0]
    )
