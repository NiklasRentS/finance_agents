from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.domain.jobs import JobStatus
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.analysis import analyse_company
from app.services.analysis_jobs import AnalysisJobService
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


@pytest.fixture
def engine() -> Iterator[Engine]:
    created = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SqlAnalysisStore(created).create_schema()
    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> SqlAnalysisStore:
    return SqlAnalysisStore(engine)


def test_job_creation_is_persisted_and_survives_a_new_store(
    store: SqlAnalysisStore, engine: Engine
) -> None:
    job = store.create_job(ticker="aapl")

    reopened = SqlAnalysisStore(engine)
    restored = reopened.get_job(job.id)

    assert restored is not None
    assert restored.ticker == "AAPL"
    assert restored.status is JobStatus.QUEUED
    assert restored.started_at is None


def test_valid_state_transitions_record_timestamps(store: SqlAnalysisStore) -> None:
    job = store.create_job(ticker="AAPL")

    running = store.transition_job(job.id, JobStatus.RUNNING, status_message="started")
    completed = store.transition_job(job.id, JobStatus.COMPLETED, status_message="done")

    assert running.started_at is not None
    assert completed.finished_at is not None
    assert completed.status_message == "done"


def test_failed_job_persists_bounded_error(store: SqlAnalysisStore) -> None:
    job = store.create_job(ticker="AAPL")
    store.transition_job(job.id, JobStatus.RUNNING)

    failed = store.transition_job(
        job.id,
        JobStatus.FAILED,
        status_message="analysis failed",
        error_message="upstream unavailable",
    )

    assert failed.status is JobStatus.FAILED
    assert failed.error_message == "upstream unavailable"
    assert failed.finished_at is not None


def test_cancelled_job_cannot_be_completed(store: SqlAnalysisStore) -> None:
    job = store.create_job(ticker="AAPL")
    store.transition_job(job.id, JobStatus.CANCELLED, status_message="user cancelled")

    with pytest.raises(ValueError, match="invalid job transition"):
        store.transition_job(job.id, JobStatus.COMPLETED)


def test_analysis_run_can_be_linked_to_completed_job(store: SqlAnalysisStore) -> None:
    analysis = analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )
    run_id = store.save_run(analysis)
    job = store.create_job(ticker="EXMP")
    store.transition_job(job.id, JobStatus.RUNNING)
    completed = store.transition_job(
        job.id, JobStatus.COMPLETED, analysis_run_id=run_id
    )

    assert completed.analysis_run_id == run_id
    assert completed.result_reference == str(run_id)


def test_service_uses_database_as_source_of_truth(store: SqlAnalysisStore) -> None:
    service = AnalysisJobService.__new__(AnalysisJobService)
    service._store = store
    job = store.create_job(ticker="MSFT")

    assert service.get(job.id) is not None
    assert service.list(limit=1)[0].id == job.id
