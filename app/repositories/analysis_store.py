"""SQLAlchemy implementation of the analysis store."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.catalysts import build_catalyst_points
from app.agents.competitive import build_competitive_summary
from app.agents.risk import build_risk_signals
from app.agents.scenarios import build_scenario_outcomes, build_thesis_statement
from app.config.settings import Settings
from app.domain.company import Company
from app.domain.facts import Confidence, FactKind, Period, SourceRef
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric, NumericFact
from app.domain.jobs import JobStatus, validate_transition
from app.ports.market_data import Quote
from app.ports.storage import AnalysisStore, RunSummary
from app.repositories.models import (
    AnalysisJobRow,
    AnalysisRunRow,
    Base,
    CompanyRow,
    RunFactRow,
    WatchlistRow,
)
from app.services.analysis import CompanyAnalysis
from app.services.valuation import DcfAssumptions, DcfResult, Multiples

_ASSUMPTIONS = TypeAdapter(DcfAssumptions)
_VALUATION = TypeAdapter(DcfResult)
_MULTIPLES = TypeAdapter(Multiples)
_QUOTE = TypeAdapter(Quote)


@dataclass(frozen=True)
class StoredRun:
    id: uuid.UUID
    ticker: str
    company_name: str
    generated_at: datetime
    currency: str | None
    assumptions: dict[str, Any]
    valuation: dict[str, Any]
    market: dict[str, Any] | None
    warnings: list[str]
    risk_signals: list[dict[str, Any]] | None
    competitive: dict[str, Any] | None
    scenarios: list[dict[str, Any]] | None
    thesis: str | None
    catalysts: list[dict[str, Any]] | None
    report_markdown: str | None


@dataclass(frozen=True)
class StoredJob:
    id: uuid.UUID
    job_type: str
    status: JobStatus
    ticker: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status_message: str | None
    error_message: str | None
    result_reference: str | None
    analysis_run_id: uuid.UUID | None


class SqlAnalysisStore(AnalysisStore):
    """Stores runs in a relational database."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> SqlAnalysisStore:
        return cls(create_engine(settings.database_url, pool_pre_ping=True))

    def create_schema(self) -> None:
        """Create all tables. Alembic owns the schema in production."""
        Base.metadata.create_all(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    def create_job(self, *, ticker: str, job_type: str = "analysis") -> StoredJob:
        row = AnalysisJobRow(
            id=uuid.uuid4(),
            job_type=job_type,
            status=JobStatus.QUEUED.value,
            ticker=ticker.strip().upper(),
            created_at=datetime.now(UTC),
            status_message="queued",
        )
        with self._sessions.begin() as session:
            session.add(row)
            session.flush()
            return _stored_job(row)

    def get_job(self, job_id: uuid.UUID) -> StoredJob | None:
        with self._sessions() as session:
            row = session.get(AnalysisJobRow, job_id)
            return None if row is None else _stored_job(row)

    def list_jobs(self, *, limit: int = 20) -> list[StoredJob]:
        statement = select(AnalysisJobRow).order_by(AnalysisJobRow.created_at.desc()).limit(limit)
        with self._sessions() as session:
            return [_stored_job(row) for row in session.scalars(statement).all()]

    def transition_job(
        self,
        job_id: uuid.UUID,
        target: JobStatus,
        *,
        status_message: str | None = None,
        error_message: str | None = None,
        analysis_run_id: uuid.UUID | None = None,
    ) -> StoredJob:
        with self._sessions.begin() as session:
            row = session.get(AnalysisJobRow, job_id)
            if row is None:
                raise KeyError(f"unknown analysis job: {job_id}")
            current = JobStatus(row.status)
            validate_transition(current, target)
            now = datetime.now(UTC)
            row.status = target.value
            row.status_message = status_message
            row.error_message = error_message
            if target is JobStatus.RUNNING:
                row.started_at = now
            if target in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                row.finished_at = now
            if analysis_run_id is not None:
                row.analysis_run_id = analysis_run_id
                row.result_reference = str(analysis_run_id)
            session.flush()
            return _stored_job(row)

    def save_run(
        self, analysis: CompanyAnalysis, *, report_markdown: str | None = None
    ) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self._sessions.begin() as session:
            company = self._company_row(session, analysis.company, analysis.ticker)
            session.add(
                AnalysisRunRow(
                    id=run_id,
                    company_id=company.id,
                    ticker=analysis.ticker,
                    generated_at=analysis.generated_at,
                    currency=analysis.history.currency,
                    period_label=analysis.latest.period.label if analysis.latest else None,
                    value_per_share=analysis.valuation.value_per_share.value,
                    assumptions=_dump(_ASSUMPTIONS, analysis.assumptions),
                    valuation=_dump(_VALUATION, analysis.valuation),
                    market=_market_document(analysis),
                    warnings=list(analysis.warnings),
                    risk_signals=[signal.__dict__ for signal in build_risk_signals(analysis)],
                    competitive=build_competitive_summary(analysis).__dict__,
                    scenarios=[scenario.__dict__ for scenario in build_scenario_outcomes(analysis)],
                    thesis=build_thesis_statement(analysis),
                    catalysts=[point.__dict__ for point in build_catalyst_points(analysis)],
                    report_markdown=report_markdown,
                    facts=_fact_rows(run_id, analysis.history),
                )
            )
        return run_id

    def list_runs(self, *, ticker: str | None = None, limit: int = 20) -> list[RunSummary]:
        statement = (
            select(AnalysisRunRow, CompanyRow.name)
            .join(CompanyRow, CompanyRow.id == AnalysisRunRow.company_id)
            .order_by(AnalysisRunRow.generated_at.desc())
            .limit(limit)
        )
        if ticker is not None:
            statement = statement.where(AnalysisRunRow.ticker == ticker.strip().upper())
        with self._sessions() as session:
            return [
                RunSummary(
                    id=row.id,
                    ticker=row.ticker,
                    company_name=name,
                    generated_at=_as_utc(row.generated_at),
                    currency=row.currency,
                    period_label=row.period_label,
                    value_per_share=row.value_per_share,
                )
                for row, name in session.execute(statement).all()
            ]

    def load_history(self, run_id: uuid.UUID) -> FinancialHistory | None:
        with self._sessions() as session:
            run = session.get(AnalysisRunRow, run_id)
            if run is None:
                return None
            facts = session.scalars(select(RunFactRow).where(RunFactRow.run_id == run_id)).all()
        return _history_from_rows(run.currency, facts)

    def load_report(self, run_id: uuid.UUID) -> str | None:
        with self._sessions() as session:
            run = session.get(AnalysisRunRow, run_id)
            return run.report_markdown if run is not None else None

    def load_latest_run(self, ticker: str) -> StoredRun | None:
        statement = (
            select(AnalysisRunRow, CompanyRow.name)
            .join(CompanyRow, CompanyRow.id == AnalysisRunRow.company_id)
            .where(AnalysisRunRow.ticker == ticker.strip().upper())
            .order_by(AnalysisRunRow.generated_at.desc())
            .limit(1)
        )
        with self._sessions() as session:
            result = session.execute(statement).first()
            if result is None:
                return None
            row, company_name = result
            return _stored_run(row, company_name)

    def load_run_document(self, run_id: uuid.UUID) -> StoredRun | None:
        statement = (
            select(AnalysisRunRow, CompanyRow.name)
            .join(CompanyRow, CompanyRow.id == AnalysisRunRow.company_id)
            .where(AnalysisRunRow.id == run_id)
        )
        with self._sessions() as session:
            result = session.execute(statement).first()
            if result is None:
                return None
            row, company_name = result
            return _stored_run(row, company_name)

    def add_watchlist_item(
        self, *, ticker: str, company_name: str, notes: str | None = None
    ) -> dict[str, str | None]:
        item = ticker.strip().upper()
        if not item:
            raise ValueError("ticker is required")
        with self._sessions.begin() as session:
            existing = session.scalars(
                select(WatchlistRow).where(WatchlistRow.ticker == item)
            ).first()
            if existing is not None:
                existing.company_name = company_name
                existing.notes = notes
                session.flush()
                return {
                    "id": str(existing.id),
                    "ticker": existing.ticker,
                    "company_name": existing.company_name,
                    "notes": existing.notes,
                }

            row = WatchlistRow(
                ticker=item,
                company_name=company_name,
                notes=notes,
            )
            session.add(row)
            session.flush()
            return {
                "id": str(row.id),
                "ticker": row.ticker,
                "company_name": row.company_name,
                "notes": row.notes,
            }

    def list_watchlist(self) -> list[dict[str, str | None]]:
        with self._sessions() as session:
            rows = session.scalars(
                select(WatchlistRow).order_by(WatchlistRow.created_at.desc())
            ).all()
            return [
                {
                    "id": str(row.id),
                    "ticker": row.ticker,
                    "company_name": row.company_name,
                    "notes": row.notes,
                }
                for row in rows
            ]

    def _company_row(self, session: Session, company: Company, ticker: str) -> CompanyRow:
        """Return the stored company, matched on CIK and otherwise on ticker."""
        existing: CompanyRow | None = None
        if company.cik is not None:
            existing = session.scalars(
                select(CompanyRow).where(CompanyRow.cik == company.cik)
            ).first()
        elif company.primary_ticker is not None:
            existing = session.scalars(
                select(CompanyRow).where(CompanyRow.primary_ticker == company.primary_ticker)
            ).first()
        if existing is not None:
            existing.name = company.name
            existing.currency = company.reporting_currency
            return existing

        row = CompanyRow(
            id=uuid.uuid4(),
            cik=company.cik,
            name=company.name,
            primary_ticker=company.primary_ticker or ticker,
            currency=company.reporting_currency,
        )
        session.add(row)
        session.flush()
        return row


def _dump[T](adapter: TypeAdapter[T], value: T) -> dict[str, Any]:
    dumped: dict[str, Any] = adapter.dump_python(value, mode="json")
    return dumped


def _market_document(analysis: CompanyAnalysis) -> dict[str, Any] | None:
    if analysis.quote is None and analysis.multiples is None:
        return None
    return {
        "quote": None if analysis.quote is None else _dump(_QUOTE, analysis.quote),
        "multiples": None if analysis.multiples is None else _dump(_MULTIPLES, analysis.multiples),
    }


def _stored_run(row: AnalysisRunRow, company_name: str) -> StoredRun:
    return StoredRun(
        id=row.id,
        ticker=row.ticker,
        company_name=company_name,
        generated_at=_as_utc(row.generated_at),
        currency=row.currency,
        assumptions=row.assumptions,
        valuation=row.valuation,
        market=row.market,
        warnings=list(row.warnings),
        risk_signals=row.risk_signals,
        competitive=row.competitive,
        scenarios=row.scenarios,
        thesis=row.thesis,
        catalysts=row.catalysts,
        report_markdown=row.report_markdown,
    )


def _stored_job(row: AnalysisJobRow) -> StoredJob:
    return StoredJob(
        id=row.id,
        job_type=row.job_type,
        status=JobStatus(row.status),
        ticker=row.ticker,
        created_at=_as_utc(row.created_at),
        started_at=None if row.started_at is None else _as_utc(row.started_at),
        finished_at=None if row.finished_at is None else _as_utc(row.finished_at),
        status_message=row.status_message,
        error_message=row.error_message,
        result_reference=row.result_reference,
        analysis_run_id=row.analysis_run_id,
    )


def _fact_rows(run_id: uuid.UUID, history: FinancialHistory) -> list[RunFactRow]:
    """One row per metric and period; a repeated period keeps the later value."""
    rows: dict[tuple[str, Any], RunFactRow] = {}
    for snapshot in history.sorted_snapshots():
        for metric, fact in snapshot.values.items():
            period = fact.period or snapshot.period
            rows[(metric.value, period.end)] = RunFactRow(
                id=uuid.uuid4(),
                run_id=run_id,
                metric=metric.value,
                period_label=period.label,
                period_end=period.end,
                value=fact.value,
                unit=fact.unit,
                kind=fact.kind.value,
                confidence=fact.confidence.value,
                note=fact.note,
                period=period.model_dump(mode="json"),
                sources=[source.model_dump(mode="json") for source in fact.sources],
            )
    return list(rows.values())


def _history_from_rows(currency: str | None, rows: Sequence[RunFactRow]) -> FinancialHistory:
    by_period: dict[Any, tuple[Period, dict[Metric, NumericFact]]] = {}
    for row in rows:
        period = Period.model_validate(row.period)
        _stored, values = by_period.setdefault(period.end, (period, {}))
        values[Metric(row.metric)] = NumericFact(
            value=row.value,
            unit=row.unit,
            period=period,
            kind=FactKind(row.kind),
            confidence=Confidence(row.confidence),
            sources=[SourceRef.model_validate(source) for source in row.sources],
            note=row.note,
        )
    return FinancialHistory(
        currency=currency,
        snapshots=[
            FinancialSnapshot(period=period, values=values)
            for period, values in sorted(by_period.values(), key=lambda item: item[0].end)
        ],
    )


def _as_utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; everything stored is UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
