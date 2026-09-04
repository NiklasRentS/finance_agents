"""Guards against the migration and the ORM models drifting apart.

Column types are dialect specific, so this compares the structure that matters
for correctness: which tables and columns the migration actually creates.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.config.settings import PROJECT_ROOT
from app.repositories.models import Base


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


def test_the_migration_creates_every_model_table(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_the_migration_creates_every_model_column(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    for name, table in Base.metadata.tables.items():
        migrated = {column["name"] for column in inspector.get_columns(name)}
        assert {column.name for column in table.columns} == migrated, f"columns differ in {name}"


def test_nullability_matches_the_models(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    for name, table in Base.metadata.tables.items():
        migrated = {column["name"]: column["nullable"] for column in inspector.get_columns(name)}
        for column in table.columns:
            assert migrated[column.name] == column.nullable, f"{name}.{column.name} differs"
