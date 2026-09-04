"""Port for price and market capitalisation data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.domain.facts import Fact, SourceRef


class Quote(BaseModel):
    """Latest known price for one listing."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    price: Fact[float]
    currency: str | None = None
    as_of: date | None = None
    source: SourceRef | None = None


class PricePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    close: float
    volume: float | None = None


class MarketDataProvider(ABC):
    """Prices only. Fundamentals belong to :class:`FundamentalsProvider`."""

    name: str

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Return the most recent price for ``ticker``."""

    @abstractmethod
    def get_historical_prices(
        self, ticker: str, *, start: date, end: date | None = None
    ) -> list[PricePoint]:
        """Return daily closing prices in chronological order."""

    @abstractmethod
    def get_market_cap(self, ticker: str) -> Fact[float]:
        """Return market capitalisation, or an N/A fact when unknown."""
