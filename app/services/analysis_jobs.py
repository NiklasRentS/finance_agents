"""Small in-process analysis job service for the personal API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from app.config.settings import Settings
from app.providers.sec_edgar import SecEdgarFundamentalsProvider
from app.providers.yahoo import YahooFinanceMarketDataProvider
from app.reporting.markdown import render_markdown
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.analysis import analyse_company


@dataclass
class AnalysisJob:
    id: uuid.UUID
    ticker: str
    status: str
    created_at: datetime
    run_id: uuid.UUID | None = None
    error: str | None = None


class AnalysisJobService:
    """Coordinates one-off analysis jobs without introducing a worker system."""

    def __init__(self, settings: Settings, store: SqlAnalysisStore) -> None:
        self._settings = settings
        self._store = store
        self._jobs: dict[uuid.UUID, AnalysisJob] = {}
        self._lock = Lock()

    def create(self, ticker: str) -> AnalysisJob:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")
        job = AnalysisJob(
            id=uuid.uuid4(),
            ticker=normalized,
            status="queued",
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: uuid.UUID) -> AnalysisJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, job_id: uuid.UUID) -> None:
        job = self.get(job_id)
        if job is None:
            return
        self._set_status(job, "running")
        fundamentals = SecEdgarFundamentalsProvider.build(self._settings)
        market_data = YahooFinanceMarketDataProvider.build(self._settings)
        try:
            analysis = analyse_company(
                job.ticker, fundamentals=fundamentals, market_data=market_data
            )
            report = render_markdown(analysis)
            job.run_id = self._store.save_run(analysis, report_markdown=report)
            self._set_status(job, "completed")
        except Exception as exc:  # background failures must become observable job state
            job.error = str(exc)
            self._set_status(job, "failed")
        finally:
            fundamentals.close()
            market_data.close()

    def _set_status(self, job: AnalysisJob, status: str) -> None:
        with self._lock:
            job.status = status

    def snapshot(self, job: AnalysisJob) -> dict[str, object]:
        return {
            "id": str(job.id),
            "ticker": job.ticker,
            "status": job.status,
            "created_at": job.created_at,
            "run_id": None if job.run_id is None else str(job.run_id),
            "error": job.error,
        }
