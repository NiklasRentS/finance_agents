from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain.broker import BrokerSnapshot
from app.providers.trade_republic.export import BrokerImportError, TradeRepublicExportProvider
from app.repositories.broker_store import SqlBrokerStore
from app.repositories.models import (
    BrokerAccountRow,
    BrokerImportRow,
    BrokerPositionRow,
    BrokerTransactionRow,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "trade_republic_v1.json"


@pytest.fixture
def engine() -> Iterator[Engine]:
    created = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    from app.repositories.models import Base

    Base.metadata.create_all(created)
    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> SqlBrokerStore:
    return SqlBrokerStore(engine)


def load_snapshot() -> BrokerSnapshot:
    return TradeRepublicExportProvider().import_snapshot(FIXTURE)


def test_valid_fixture_maps_to_normalized_models() -> None:
    snapshot = load_snapshot()

    assert snapshot.account.account_identifier == "fixture-account-001"
    assert len(snapshot.positions) == 2
    assert snapshot.positions[0].quantity == Decimal("10.5")
    assert {cash.currency for cash in snapshot.cash_balances} == {"EUR", "USD"}
    assert len(snapshot.transactions) == 3


def test_import_persists_positions_transactions_and_summary(
    store: SqlBrokerStore, engine: Engine
) -> None:
    result = store.import_snapshot(load_snapshot(), source=FIXTURE)

    assert result.records_read == 3
    assert result.records_new == 3
    assert result.records_duplicate == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(BrokerAccountRow)) == 1
        assert session.scalar(select(func.count()).select_from(BrokerPositionRow)) == 2
        assert session.scalar(select(func.count()).select_from(BrokerTransactionRow)) == 3
        import_row = session.scalar(select(BrokerImportRow))
    assert import_row is not None
    assert import_row.records_new == 3
    assert import_row.errors == []


def test_repeating_the_same_import_is_idempotent(store: SqlBrokerStore, engine: Engine) -> None:
    first = store.import_snapshot(load_snapshot(), source=FIXTURE)
    second = store.import_snapshot(load_snapshot(), source=FIXTURE)

    assert first.records_new == 3
    assert second.records_new == 0
    assert second.records_duplicate == 3
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(BrokerTransactionRow)) == 3
        assert session.scalar(select(func.count()).select_from(BrokerImportRow)) == 2


def test_transactions_without_external_id_use_a_stable_fingerprint() -> None:
    snapshot = load_snapshot()
    transaction = snapshot.transactions[1]
    assert transaction.external_id is None

    from app.repositories.broker_store import transaction_fingerprint

    assert transaction_fingerprint(transaction) == transaction_fingerprint(transaction)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del payload["data"]["account"]["currency"]
    source = tmp_path / "missing.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BrokerImportError, match="does not match"):
        TradeRepublicExportProvider().import_snapshot(source)


def test_invalid_transaction_row_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["data"]["transactions"][0]["currency"] = "EURO"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BrokerImportError, match="does not match"):
        TradeRepublicExportProvider().import_snapshot(source)


def test_unknown_format_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "unknown.json"
    source.write_text(json.dumps({"format": "trade-republic-private-api"}), encoding="utf-8")

    with pytest.raises(BrokerImportError, match="unsupported export format"):
        TradeRepublicExportProvider().import_snapshot(source)
