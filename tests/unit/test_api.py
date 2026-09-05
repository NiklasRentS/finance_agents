from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.providers.trade_republic.export import TradeRepublicExportProvider
from app.repositories.analysis_store import SqlAnalysisStore
from app.repositories.broker_store import SqlBrokerStore
from app.services.analysis import analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


@pytest.fixture
def engine() -> Iterator[Engine]:
    created = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> Iterator[SqlAnalysisStore]:
    store = SqlAnalysisStore(engine)
    store.create_schema()
    yield store
    store.close()


def _analysis(ticker: str = "EXMP") -> object:
    return analyse_company(
        ticker,
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )


def _broker_store(engine: Engine) -> SqlBrokerStore:
    return SqlBrokerStore(engine)


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


def test_portfolio_endpoints_expose_local_import_as_read_only_data(
    store: SqlAnalysisStore, engine: Engine
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "trade_republic_v1.json"
    broker_store = _broker_store(engine)
    snapshot = TradeRepublicExportProvider().import_snapshot(fixture)
    broker_store.import_snapshot(snapshot, source=fixture)

    client = TestClient(create_app(store=store, broker_store=broker_store))
    portfolio = client.get("/api/v1/portfolio")
    positions = client.get("/api/v1/portfolio/positions?account_identifier=fixture-account-001")
    transactions = client.get("/api/v1/portfolio/transactions")
    imports = client.get("/api/v1/portfolio/imports")

    assert portfolio.status_code == 200
    assert len(portfolio.json()["positions"]) == 2
    assert {item["currency"] for item in portfolio.json()["cash"]} == {"EUR", "USD"}
    assert positions.json()[0]["isin"]
    assert len(transactions.json()) == 3
    assert imports.json()[0]["records_new"] == 3


def test_stock_endpoints_expose_structured_research_without_parsing_markdown(
    store: SqlAnalysisStore,
) -> None:
    run_id = store.save_run(_analysis("AAPL"), report_markdown="# Human report")
    client = TestClient(create_app(store=store))

    stock = client.get("/api/v1/stocks/AAPL")
    financials = client.get("/api/v1/stocks/AAPL/financials")
    valuation = client.get("/api/v1/stocks/AAPL/valuation")
    report = client.get("/api/v1/stocks/AAPL/reports")

    assert stock.status_code == 200
    assert stock.json()["run_id"] == str(run_id)
    assert stock.json()["financials"]
    assert stock.json()["sources"]
    assert financials.json()[-1]["values"]["revenue"]["value"] is not None
    assert valuation.json()["valuation"]["value_per_share"]
    assert report.json() == {"run_id": str(run_id), "markdown": "# Human report"}


def test_persistent_analysis_job_endpoints_list_and_cancel(store: SqlAnalysisStore) -> None:
    job = store.create_job(ticker="AAPL")
    client = TestClient(create_app(store=store))

    listed = client.get("/api/v1/analysis")
    cancelled = client.post(f"/api/v1/analysis/{job.id}/cancel")
    status = client.get(f"/api/v1/analysis/{job.id}")

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == str(job.id)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert status.json()["status"] == "cancelled"
