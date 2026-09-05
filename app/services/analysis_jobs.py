"""Persistent one-off analysis job service for the personal API."""

from __future__ import annotations

import uuid
from typing import Any

from app.config.settings import Settings
from app.domain.jobs import JobStatus
from app.providers.sec_edgar import SecEdgarFundamentalsProvider
from app.providers.yahoo import YahooFinanceMarketDataProvider
from app.reporting.markdown import render_markdown
from app.repositories.analysis_store import SqlAnalysisStore, StoredJob
from app.services.analysis import analyse_company


class AnalysisJobService:
    """Coordinates analysis jobs whose source of truth is PostgreSQL."""

    def __init__(self, settings: Settings, store: SqlAnalysisStore) -> None:
        self._settings = settings
        self._store = store

    def create(self, ticker: str) -> StoredJob:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")
        return self._store.create_job(ticker=normalized)

    def get(self, job_id: uuid.UUID) -> StoredJob | None:
        return self._store.get_job(job_id)

    def list(self, *, limit: int = 20) -> list[StoredJob]:
        return self._store.list_jobs(limit=limit)

    def cancel(self, job_id: uuid.UUID) -> StoredJob:
        return self._store.transition_job(
            job_id,
            JobStatus.CANCELLED,
            status_message="cancelled by user",
        )

    def run(self, job_id: uuid.UUID) -> None:
        job = self.get(job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            return
        try:
            job = self._store.transition_job(
                job_id, JobStatus.RUNNING, status_message="analysis started"
            )
        except (KeyError, ValueError):
            return

        fundamentals = SecEdgarFundamentalsProvider.build(self._settings)
        market_data = YahooFinanceMarketDataProvider.build(self._settings)
        try:
            analysis = analyse_company(
                job.ticker, fundamentals=fundamentals, market_data=market_data
            )
            report = render_markdown(analysis)
            run_id = self._store.save_run(analysis, report_markdown=report)
            self._store.transition_job(
                job_id,
                JobStatus.COMPLETED,
                status_message="analysis completed",
                analysis_run_id=run_id,
            )
        except Exception as exc:  # background failures must become observable job state
            current = self.get(job_id)
            if current is not None and current.status is JobStatus.RUNNING:
                self._store.transition_job(
                    job_id,
                    JobStatus.FAILED,
                    status_message="analysis failed",
                    error_message=_safe_error(exc),
                )
        finally:
            fundamentals.close()
            market_data.close()

    @staticmethod
    def snapshot(job: StoredJob) -> dict[str, Any]:
        return {
            "id": str(job.id),
            "job_type": job.job_type,
            "ticker": job.ticker,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "started_at": None if job.started_at is None else job.started_at.isoformat(),
            "finished_at": None if job.finished_at is None else job.finished_at.isoformat(),
            "status_message": job.status_message,
            "error": job.error_message,
            "result_reference": job.result_reference,
            "run_id": None if job.analysis_run_id is None else str(job.analysis_run_id),
        }


def _safe_error(error: Exception) -> str:
    """Persist a bounded diagnostic, never a traceback or credential payload."""
    return str(error).replace("\r", " ").replace("\n", " ")[:1000]
