"""Local persistence for normalized broker imports."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings
from app.domain.broker import BrokerSnapshot, CashBalance, Instrument, Position, Transaction
from app.repositories.models import (
    BrokerAccountRow,
    BrokerCashBalanceRow,
    BrokerImportRow,
    BrokerInstrumentRow,
    BrokerPositionRow,
    BrokerTransactionRow,
)


class BrokerImportResult:
    def __init__(
        self,
        *,
        import_id: uuid.UUID,
        records_read: int,
        records_new: int,
        records_duplicate: int,
        errors: list[str],
    ) -> None:
        self.import_id = import_id
        self.records_read = records_read
        self.records_new = records_new
        self.records_duplicate = records_duplicate
        self.errors = errors


class SqlBrokerStore:
    """Stores broker data locally and never exposes write operations to brokers."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> SqlBrokerStore:
        from sqlalchemy import create_engine

        return cls(create_engine(settings.database_url, pool_pre_ping=True))

    def list_positions(self, *, account_identifier: str | None = None) -> list[dict[str, object]]:
        statement = (
            select(BrokerPositionRow, BrokerInstrumentRow, BrokerAccountRow)
            .join(BrokerInstrumentRow, BrokerInstrumentRow.id == BrokerPositionRow.instrument_id)
            .join(BrokerAccountRow, BrokerAccountRow.id == BrokerPositionRow.account_id)
            .order_by(BrokerInstrumentRow.ticker, BrokerInstrumentRow.isin)
        )
        if account_identifier is not None:
            statement = statement.where(
                BrokerAccountRow.account_identifier == account_identifier.strip()
            )
        with self._sessions() as session:
            return [
                {
                    "account_identifier": account.account_identifier,
                    "broker": account.broker,
                    "isin": instrument.isin,
                    "ticker": instrument.ticker,
                    "name": instrument.name,
                    "instrument_currency": instrument.currency,
                    "quantity": position.quantity,
                    "average_cost": position.average_cost,
                    "current_value": position.current_value,
                    "currency": position.currency,
                    "imported_at": position.imported_at,
                }
                for position, instrument, account in session.execute(statement).all()
            ]

    def list_cash_balances(
        self, *, account_identifier: str | None = None
    ) -> list[dict[str, object]]:
        statement = (
            select(BrokerCashBalanceRow, BrokerAccountRow)
            .join(BrokerAccountRow, BrokerAccountRow.id == BrokerCashBalanceRow.account_id)
            .order_by(BrokerCashBalanceRow.currency)
        )
        if account_identifier is not None:
            statement = statement.where(
                BrokerAccountRow.account_identifier == account_identifier.strip()
            )
        with self._sessions() as session:
            return [
                {
                    "account_identifier": account.account_identifier,
                    "broker": account.broker,
                    "amount": cash.amount,
                    "currency": cash.currency,
                    "imported_at": cash.imported_at,
                }
                for cash, account in session.execute(statement).all()
            ]

    def list_transactions(
        self, *, account_identifier: str | None = None
    ) -> list[dict[str, object]]:
        statement = (
            select(BrokerTransactionRow, BrokerInstrumentRow, BrokerAccountRow)
            .join(BrokerAccountRow, BrokerAccountRow.id == BrokerTransactionRow.account_id)
            .outerjoin(
                BrokerInstrumentRow, BrokerInstrumentRow.id == BrokerTransactionRow.instrument_id
            )
            .order_by(BrokerTransactionRow.timestamp.desc())
        )
        if account_identifier is not None:
            statement = statement.where(
                BrokerAccountRow.account_identifier == account_identifier.strip()
            )
        with self._sessions() as session:
            return [
                {
                    "account_identifier": account.account_identifier,
                    "broker": account.broker,
                    "timestamp": transaction.timestamp,
                    "transaction_type": transaction.transaction_type,
                    "isin": instrument.isin if instrument is not None else None,
                    "ticker": instrument.ticker if instrument is not None else None,
                    "quantity": transaction.quantity,
                    "price": transaction.price,
                    "fees": transaction.fees,
                    "taxes": transaction.taxes,
                    "currency": transaction.currency,
                    "external_id": transaction.external_id,
                    "source": transaction.source,
                }
                for transaction, instrument, account in session.execute(statement).all()
            ]

    def list_imports(self) -> list[dict[str, object]]:
        statement = select(BrokerImportRow, BrokerAccountRow).join(
            BrokerAccountRow, BrokerAccountRow.id == BrokerImportRow.account_id
        ).order_by(BrokerImportRow.imported_at.desc())
        with self._sessions() as session:
            return [
                {
                    "id": row.id,
                    "account_identifier": account.account_identifier,
                    "broker": row.broker,
                    "source": row.source,
                    "imported_at": row.imported_at,
                    "records_read": row.records_read,
                    "records_new": row.records_new,
                    "records_duplicate": row.records_duplicate,
                    "errors": row.errors,
                }
                for row, account in session.execute(statement).all()
            ]

    def import_snapshot(
        self, snapshot: BrokerSnapshot, *, source: Path | str
    ) -> BrokerImportResult:
        source_name = Path(source).name
        import_id = uuid.uuid4()
        transactions = snapshot.transactions
        errors: list[str] = []
        records_new = 0
        records_duplicate = 0
        with self._sessions.begin() as session:
            account = session.scalars(
                select(BrokerAccountRow).where(
                    BrokerAccountRow.broker == snapshot.account.broker.value,
                    BrokerAccountRow.account_identifier
                    == snapshot.account.account_identifier,
                )
            ).first()
            if account is None:
                account = BrokerAccountRow(
                    id=uuid.uuid4(),
                    broker=snapshot.account.broker.value,
                    account_identifier=snapshot.account.account_identifier,
                    currency=snapshot.account.currency,
                )
                session.add(account)
                session.flush()

            for position in snapshot.positions:
                instrument = self._instrument(session, position)
                self._upsert_position(session, account.id, instrument.id, position)
            for cash in snapshot.cash_balances:
                self._upsert_cash(session, account.id, cash)

            for transaction in transactions:
                fingerprint = transaction_fingerprint(transaction)
                existing = session.scalars(
                    select(BrokerTransactionRow).where(
                        BrokerTransactionRow.account_id == account.id,
                        BrokerTransactionRow.fingerprint == fingerprint,
                    )
                ).first()
                if existing is not None:
                    records_duplicate += 1
                    continue
                instrument_id = None
                if transaction.instrument is not None:
                    instrument_id = self._instrument_from_transaction(session, transaction).id
                session.add(
                    BrokerTransactionRow(
                        id=uuid.uuid4(),
                        account_id=account.id,
                        instrument_id=instrument_id,
                        timestamp=transaction.timestamp,
                        transaction_type=transaction.transaction_type.value,
                        quantity=transaction.quantity,
                        price=transaction.price,
                        fees=transaction.fees,
                        taxes=transaction.taxes,
                        currency=transaction.currency,
                        external_id=transaction.external_id,
                        fingerprint=fingerprint,
                        source=transaction.source,
                        import_id=import_id,
                    )
                )
                records_new += 1

            session.add(
                BrokerImportRow(
                    id=import_id,
                    account_id=account.id,
                    broker=snapshot.account.broker.value,
                    source=source_name,
                    imported_at=datetime.now(UTC),
                    records_read=len(transactions),
                    records_new=records_new,
                    records_duplicate=records_duplicate,
                    errors=errors,
                )
            )
        return BrokerImportResult(
            import_id=import_id,
            records_read=len(transactions),
            records_new=records_new,
            records_duplicate=records_duplicate,
            errors=errors,
        )

    def _instrument(self, session: Session, position: Position) -> BrokerInstrumentRow:
        return self._instrument_by_model(session, position.instrument)

    def _instrument_from_transaction(
        self, session: Session, transaction: Transaction
    ) -> BrokerInstrumentRow:
        assert transaction.instrument is not None
        return self._instrument_by_model(session, transaction.instrument)

    def _instrument_by_model(self, session: Session, instrument: Instrument) -> BrokerInstrumentRow:
        row = session.scalars(
            select(BrokerInstrumentRow).where(BrokerInstrumentRow.isin == instrument.isin)
        ).first()
        if row is None:
            row = BrokerInstrumentRow(
                id=uuid.uuid4(),
                isin=instrument.isin,
                ticker=instrument.ticker,
                name=instrument.name,
                currency=instrument.currency,
            )
            session.add(row)
            session.flush()
        return row

    @staticmethod
    def _upsert_position(
        session: Session, account_id: uuid.UUID, instrument_id: uuid.UUID, position: Position
    ) -> None:
        row = session.scalars(
            select(BrokerPositionRow).where(
                BrokerPositionRow.account_id == account_id,
                BrokerPositionRow.instrument_id == instrument_id,
            )
        ).first()
        values = {
            "quantity": position.quantity,
            "average_cost": position.average_cost,
            "current_value": position.current_value,
            "currency": position.currency,
            "imported_at": position.imported_at,
        }
        if row is None:
            session.add(
                BrokerPositionRow(
                    id=uuid.uuid4(), account_id=account_id, instrument_id=instrument_id, **values
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)

    @staticmethod
    def _upsert_cash(session: Session, account_id: uuid.UUID, cash: CashBalance) -> None:
        row = session.scalars(
            select(BrokerCashBalanceRow).where(
                BrokerCashBalanceRow.account_id == account_id,
                BrokerCashBalanceRow.currency == cash.currency,
            )
        ).first()
        if row is None:
            session.add(
                BrokerCashBalanceRow(
                    id=uuid.uuid4(),
                    account_id=account_id,
                    amount=cash.amount,
                    currency=cash.currency,
                    imported_at=cash.imported_at,
                )
            )
        else:
            row.amount = cash.amount
            row.imported_at = cash.imported_at


def transaction_fingerprint(transaction: Transaction) -> str:
    """Build a stable key when an export does not provide an external ID."""
    if transaction.external_id:
        return f"external:{transaction.external_id}"
    document = {
        "account": transaction.account_identifier,
        "timestamp": transaction.timestamp.isoformat(),
        "type": transaction.transaction_type.value,
        "isin": transaction.instrument.isin if transaction.instrument else None,
        "quantity": str(transaction.quantity) if transaction.quantity is not None else None,
        "price": str(transaction.price) if transaction.price is not None else None,
        "fees": str(transaction.fees),
        "taxes": str(transaction.taxes),
        "currency": transaction.currency,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return "fingerprint:" + hashlib.sha256(encoded).hexdigest()