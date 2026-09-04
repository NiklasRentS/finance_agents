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
    """Prices only.

    Market capitalisation is deliberately absent: it is derived from a price and
    a share count, each of which carries its own source.
    """

    name: str

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Return the most recent price for ``ticker``."""

    @abstractmethod
    def get_historical_prices(
        self, ticker: str, *, start: date, end: date | None = None
    ) -> list[PricePoint]:
        """Return daily closing prices in chronological order."""
