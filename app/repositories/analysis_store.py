"""SQLAlchemy implementation of the analysis store."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings
from app.domain.company import Company
from app.domain.facts import Confidence, FactKind, Period, SourceRef
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric, NumericFact
from app.ports.market_data import Quote
from app.ports.storage import AnalysisStore, RunSummary
from app.repositories.models import AnalysisRunRow, Base, CompanyRow, RunFactRow
from app.services.analysis import CompanyAnalysis
from app.services.valuation import DcfAssumptions, DcfResult, Multiples

_ASSUMPTIONS = TypeAdapter(DcfAssumptions)
_VALUATION = TypeAdapter(DcfResult)
_MULTIPLES = TypeAdapter(Multiples)
_QUOTE = TypeAdapter(Quote)


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
