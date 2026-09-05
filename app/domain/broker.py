"""Broker-independent, read-only portfolio models.

These models describe imported data only. They intentionally contain no
operation that could mutate a broker account.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BrokerName(StrEnum):
    TRADE_REPUBLIC = "trade_republic"


class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    TAX = "tax"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTEREST = "interest"
    OTHER = "other"


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    isin: str = Field(min_length=12, max_length=12)
    ticker: str | None = None
    name: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)


class BrokerAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker: BrokerName
    account_identifier: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_identifier: str = Field(min_length=1)
    instrument: Instrument
    quantity: Decimal = Field(ge=0)
    average_cost: Decimal = Field(ge=0)
    current_value: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    imported_at: datetime


class CashBalance(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_identifier: str = Field(min_length=1)
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    imported_at: datetime


class Transaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_identifier: str = Field(min_length=1)
    timestamp: datetime
    transaction_type: TransactionType
    instrument: Instrument | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    price: Decimal | None = Field(default=None, ge=0)
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    taxes: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(min_length=3, max_length=3)
    external_id: str | None = None
    source: str = Field(min_length=1)


class BrokerSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    account: BrokerAccount
    positions: list[Position] = Field(default_factory=list)
    cash_balances: list[CashBalance] = Field(default_factory=list)
    transactions: list[Transaction] = Field(default_factory=list)