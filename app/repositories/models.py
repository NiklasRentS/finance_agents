"""Relational schema for stored analysis runs.

Facts are stored one row per metric and period rather than as one JSON blob per
run, so later queries can ask "how did revenue for FY2024 change between runs"
without unpacking every document.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")

# asdecimal=False keeps one Python type across dialects; the domain works in
# floats anyway and no reported figure comes close to that precision limit.
NUMBER_TYPE = Numeric(38, 10, asdecimal=False)


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CompanyRow(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str | None] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    primary_ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    currency: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    runs: Mapped[list[AnalysisRunRow]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currency: Mapped[str | None] = mapped_column(String(8))
    period_label: Mapped[str | None] = mapped_column(String(32))

    # Denormalised so run lists do not have to parse the valuation document.
    value_per_share: Mapped[float | None] = mapped_column(NUMBER_TYPE)

    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    valuation: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    market: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    warnings: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    report_markdown: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    company: Mapped[CompanyRow] = relationship(back_populates="runs")
    facts: Mapped[list[RunFactRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RunFactRow(Base):
    """One metric of one period, including the sources it came from."""

    __tablename__ = "run_facts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(String(64))
    period_label: Mapped[str] = mapped_column(String(32))
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(NUMBER_TYPE)
    unit: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    period: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE)

    run: Mapped[AnalysisRunRow] = relationship(back_populates="facts")

    __table_args__ = (
        UniqueConstraint("run_id", "metric", "period_end", name="uq_run_facts_metric_period"),
        Index("ix_run_facts_metric_period_end", "metric", "period_end"),
    )
