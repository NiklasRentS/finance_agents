"""Read-only portfolio endpoints backed by local broker imports."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.repositories.broker_store import SqlBrokerStore
from app.services.portfolio import PortfolioService


class PositionResponse(BaseModel):
    account_identifier: str
    broker: str
    isin: str
    ticker: str | None
    name: str
    instrument_currency: str
    quantity: Decimal
    average_cost: Decimal
    current_value: Decimal
    currency: str
    imported_at: datetime


class CashResponse(BaseModel):
    account_identifier: str
    broker: str
    amount: Decimal
    currency: str
    imported_at: datetime


class TransactionResponse(BaseModel):
    account_identifier: str
    broker: str
    timestamp: datetime
    transaction_type: str
    isin: str | None
    ticker: str | None
    quantity: Decimal | None
    price: Decimal | None
    fees: Decimal
    taxes: Decimal
    currency: str
    external_id: str | None
    source: str


class ImportResponse(BaseModel):
    id: UUID
    account_identifier: str
    broker: str
    source: str
    imported_at: datetime
    records_read: int
    records_new: int
    records_duplicate: int
    errors: list[str]


def build_portfolio_router(store: SqlBrokerStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])
    service = PortfolioService(store)

    @router.get("/positions", response_model=list[PositionResponse])
    def positions(
        account_identifier: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return service.positions(account_identifier=account_identifier)

    @router.get("/cash", response_model=list[CashResponse])
    def cash(
        account_identifier: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return service.cash(account_identifier=account_identifier)

    @router.get("/transactions", response_model=list[TransactionResponse])
    def transactions(
        account_identifier: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return service.transactions(account_identifier=account_identifier)

    @router.get("/imports", response_model=list[ImportResponse])
    def imports() -> list[dict[str, Any]]:
        return service.imports()

    @router.get("", response_model=dict[str, list[Any]])
    def portfolio(
        account_identifier: str | None = Query(default=None),
    ) -> dict[str, list[Any]]:
        return {
            "positions": positions(account_identifier),
            "cash": cash(account_identifier),
        }

    return router