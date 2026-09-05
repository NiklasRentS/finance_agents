"""read-only broker import schema

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NUMBER_TYPE = sa.Numeric(38, 10, asdecimal=False)


def upgrade() -> None:
    op.create_table(
        "broker_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("account_identifier", sa.String(length=128), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker", "account_identifier"),
    )
    op.create_table(
        "broker_instruments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin"),
    )
    op.create_table(
        "broker_positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", NUMBER_TYPE, nullable=False),
        sa.Column("average_cost", NUMBER_TYPE, nullable=False),
        sa.Column("current_value", NUMBER_TYPE, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["broker_instruments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "instrument_id"),
    )
    op.create_table(
        "broker_cash_balances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", NUMBER_TYPE, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "currency"),
    )
    op.create_table(
        "broker_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("records_read", sa.Integer(), nullable=False),
        sa.Column("records_new", sa.Integer(), nullable=False),
        sa.Column("records_duplicate", sa.Integer(), nullable=False),
        sa.Column("errors", JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "broker_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("quantity", NUMBER_TYPE, nullable=True),
        sa.Column("price", NUMBER_TYPE, nullable=True),
        sa.Column("fees", NUMBER_TYPE, nullable=False),
        sa.Column("taxes", NUMBER_TYPE, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["broker_instruments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["import_id"], ["broker_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "fingerprint"),
    )


def downgrade() -> None:
    op.drop_table("broker_transactions")
    op.drop_table("broker_imports")
    op.drop_table("broker_cash_balances")
    op.drop_table("broker_positions")
    op.drop_table("broker_instruments")
    op.drop_table("broker_accounts")