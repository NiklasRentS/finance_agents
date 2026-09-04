"""initial analysis run schema

Revision ID: 0001
Revises:
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NUMBER_TYPE = sa.Numeric(38, 10, asdecimal=False)


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("primary_ticker", sa.String(length=16), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cik"),
    )
    op.create_index("ix_companies_primary_ticker", "companies", ["primary_ticker"])

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("period_label", sa.String(length=32), nullable=True),
        sa.Column("value_per_share", NUMBER_TYPE, nullable=True),
        sa.Column("assumptions", JSON_TYPE, nullable=False),
        sa.Column("valuation", JSON_TYPE, nullable=False),
        sa.Column("market", JSON_TYPE, nullable=True),
        sa.Column("warnings", JSON_TYPE, nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_company_id", "analysis_runs", ["company_id"])
    op.create_index("ix_analysis_runs_generated_at", "analysis_runs", ["generated_at"])
    op.create_index("ix_analysis_runs_ticker", "analysis_runs", ["ticker"])

    op.create_table(
        "run_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", NUMBER_TYPE, nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("period", JSON_TYPE, nullable=False),
        sa.Column("sources", JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "metric", "period_end", name="uq_run_facts_metric_period"),
    )
    op.create_index("ix_run_facts_run_id", "run_facts", ["run_id"])
    op.create_index("ix_run_facts_metric_period_end", "run_facts", ["metric", "period_end"])


def downgrade() -> None:
    op.drop_table("run_facts")
    op.drop_table("analysis_runs")
    op.drop_table("companies")
