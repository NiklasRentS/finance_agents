"""API routes for starting and observing one personal analysis job."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import Settings
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.analysis_jobs import AnalysisJobService


class AnalysisRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=16)


class AnalysisJobResponse(BaseModel):
    id: str
    job_type: str
    ticker: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    status_message: str | None
    run_id: str | None
    result_reference: str | None
    error: str | None


def build_analysis_router(settings: Settings, store: SqlAnalysisStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])
    service = AnalysisJobService(settings, store)

    @router.post("", response_model=AnalysisJobResponse, status_code=202)
    def start_analysis(
        payload: AnalysisRequest, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        try:
            job = service.create(payload.ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        background_tasks.add_task(service.run, job.id)
        return service.snapshot(job)

    @router.get("/{job_id}", response_model=AnalysisJobResponse)
    def analysis_status(job_id: str) -> dict[str, Any]:
        try:
            identifier = uuid.UUID(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid job id") from exc
        job = service.get(identifier)
        if job is None:
            raise HTTPException(status_code=404, detail="analysis job not found")
        return service.snapshot(job)

    @router.get("", response_model=list[AnalysisJobResponse])
    def list_analysis_jobs(limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
        return [service.snapshot(job) for job in service.list(limit=limit)]

    @router.post("/{job_id}/cancel", response_model=AnalysisJobResponse)
    def cancel_analysis(job_id: str) -> dict[str, Any]:
        try:
            identifier = uuid.UUID(job_id)
            return service.snapshot(service.cancel(identifier))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="analysis job not found") from exc

    return router
