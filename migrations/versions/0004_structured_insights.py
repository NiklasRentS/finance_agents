"""structured research insight documents

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("risk_signals", JSON_TYPE, nullable=True))
    op.add_column("analysis_runs", sa.Column("competitive", JSON_TYPE, nullable=True))
    op.add_column("analysis_runs", sa.Column("scenarios", JSON_TYPE, nullable=True))
    op.add_column("analysis_runs", sa.Column("thesis", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_runs", "thesis")
    op.drop_column("analysis_runs", "scenarios")
    op.drop_column("analysis_runs", "competitive")
    op.drop_column("analysis_runs", "risk_signals")