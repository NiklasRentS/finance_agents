"""Application service for read-only imported portfolio data."""

from __future__ import annotations

from typing import Any

from app.repositories.broker_store import SqlBrokerStore


class PortfolioService:
    """Expose broker data to application adapters without broker write methods."""

    def __init__(self, store: SqlBrokerStore) -> None:
        self._store = store

    def positions(self, *, account_identifier: str | None = None) -> list[dict[str, Any]]:
        return self._store.list_positions(account_identifier=account_identifier)

    def cash(self, *, account_identifier: str | None = None) -> list[dict[str, Any]]:
        return self._store.list_cash_balances(account_identifier=account_identifier)

    def transactions(self, *, account_identifier: str | None = None) -> list[dict[str, Any]]:
        return self._store.list_transactions(account_identifier=account_identifier)

    def imports(self) -> list[dict[str, Any]]:
        return self._store.list_imports()