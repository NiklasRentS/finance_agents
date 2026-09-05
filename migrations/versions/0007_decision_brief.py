"""persist deterministic investment decision brief

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("decision_brief", JSON_TYPE, nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_runs", "decision_brief")