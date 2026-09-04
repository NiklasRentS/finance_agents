"""Tests for the analysis store.

These run against SQLite so the suite stays offline; the Postgres schema itself
is covered by the migration integration test.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from pydantic import TypeAdapter
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain.financials import Metric
from app.repositories.analysis_store import SqlAnalysisStore
from app.repositories.models import AnalysisRunRow, CompanyRow, RunFactRow
from app.services.analysis import CompanyAnalysis, analyse_company
from app.services.valuation import DcfResult
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


@pytest.fixture
def engine() -> Iterator[Engine]:
    created = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> SqlAnalysisStore:
    instance = SqlAnalysisStore(engine)
    instance.create_schema()
    return instance


def _analysis(*, omit: set[Metric] | None = None, fail_market: bool = False) -> CompanyAnalysis:
    return analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(omit=omit),
        market_data=ConfigurableFakeMarketData(fail=fail_market),
    )


class TestSavingRuns:
    def test_a_saved_run_can_be_listed(self, store: SqlAnalysisStore) -> None:
        run_id = store.save_run(_analysis())
        summaries = store.list_runs()
        assert [summary.id for summary in summaries] == [run_id]
        assert summaries[0].ticker == "EXMP"
        assert summaries[0].company_name == "Example Corp."
        assert summaries[0].period_label == "FY2025"

    def test_the_valuation_result_is_listed_without_loading_the_run(
        self, store: SqlAnalysisStore
    ) -> None:
        analysis = _analysis()
        store.save_run(analysis)
        summary = store.list_runs()[0]
        assert summary.value_per_share == pytest.approx(analysis.valuation.value_per_share.value)
        assert summary.currency == "USD"

    def test_the_report_is_stored_verbatim(self, store: SqlAnalysisStore) -> None:
        run_id = store.save_run(_analysis(), report_markdown="# Bericht\n\nInhalt")
        assert store.load_report(run_id) == "# Bericht\n\nInhalt"

    def test_a_run_without_a_report_stores_none(self, store: SqlAnalysisStore) -> None:
        assert store.load_report(store.save_run(_analysis())) is None

    def test_warnings_are_stored_with_the_run(
        self, store: SqlAnalysisStore, engine: Engine
    ) -> None:
        analysis = _analysis(fail_market=True)
        assert analysis.warnings, "the fake is configured to fail on market data"
        run_id = store.save_run(analysis)
        with Session(engine) as session:
            row = session.get(AnalysisRunRow, run_id)
        assert row is not None
        assert row.warnings == list(analysis.warnings)
        assert row.market is None

    def test_the_valuation_document_is_lossless(
        self, store: SqlAnalysisStore, engine: Engine
    ) -> None:
        analysis = _analysis()
        run_id = store.save_run(analysis)
        with Session(engine) as session:
            row = session.get(AnalysisRunRow, run_id)
        assert row is not None
        restored = TypeAdapter(DcfResult).validate_python(row.valuation)
        assert restored.value_per_share.value == pytest.approx(
            analysis.valuation.value_per_share.value
        )
        assert restored.assumptions.wacc == analysis.assumptions.wacc
        assert restored.value_per_share.sources == analysis.valuation.value_per_share.sources


class TestRoundTrip:
    def test_values_are_restored_unchanged(self, store: SqlAnalysisStore) -> None:
        analysis = _analysis()
        history = store.load_history(store.save_run(analysis))
        original = analysis.latest
        assert history is not None
        assert original is not None
        restored = history.sorted_snapshots()[-1]
        assert restored.get(Metric.REVENUE).value == pytest.approx(
            original.get(Metric.REVENUE).value
        )
        assert restored.get(Metric.ROIC).value == pytest.approx(original.get(Metric.ROIC).value)

    def test_provenance_is_restored(self, store: SqlAnalysisStore) -> None:
        analysis = _analysis()
        history = store.load_history(store.save_run(analysis))
        original = analysis.latest
        assert history is not None
        assert original is not None
        restored = history.sorted_snapshots()[-1].get(Metric.REVENUE)
        assert restored.sources == original.get(Metric.REVENUE).sources
        assert restored.kind is original.get(Metric.REVENUE).kind
        assert restored.confidence is original.get(Metric.REVENUE).confidence

    def test_every_period_is_kept(self, store: SqlAnalysisStore) -> None:
        analysis = _analysis()
        history = store.load_history(store.save_run(analysis))
        assert history is not None
        assert [snapshot.period.label for snapshot in history.sorted_snapshots()] == [
            snapshot.period.label for snapshot in analysis.history.sorted_snapshots()
        ]

    def test_unavailable_metrics_stay_unavailable(self, store: SqlAnalysisStore) -> None:
        analysis = _analysis(omit={Metric.LONG_TERM_DEBT})
        history = store.load_history(store.save_run(analysis))
        assert history is not None
        assert not history.sorted_snapshots()[-1].get(Metric.LONG_TERM_DEBT).is_available

    def test_an_unknown_run_is_not_invented(self, store: SqlAnalysisStore) -> None:
        assert store.load_history(uuid.uuid4()) is None
        assert store.load_report(uuid.uuid4()) is None


class TestListing:
    def test_runs_are_filtered_by_ticker(self, store: SqlAnalysisStore) -> None:
        store.save_run(_analysis())
        assert store.list_runs(ticker="exmp")
        assert store.list_runs(ticker="OTHER") == []

    def test_limit_is_respected(self, store: SqlAnalysisStore) -> None:
        for _ in range(3):
            store.save_run(_analysis())
        assert len(store.list_runs(limit=2)) == 2

    def test_repeated_runs_reuse_the_company(self, store: SqlAnalysisStore, engine: Engine) -> None:
        store.save_run(_analysis())
        store.save_run(_analysis())
        with Session(engine) as session:
            companies = session.scalars(select(CompanyRow)).all()
            facts = session.scalars(select(RunFactRow)).all()
        assert len(companies) == 1
        assert len(facts) > 0
