"""Company identity and listing information."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.facts import Fact, SourceRef


class Listing(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: str | None = None
    currency: str | None = None
    is_primary: bool = True

    @field_validator("ticker")
    @classmethod
    def _normalise_ticker(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("ticker must not be empty")
        return cleaned


class Company(BaseModel):
    """Resolved company identity shared by every agent in a run."""

    name: str
    listings: list[Listing] = Field(default_factory=list)
    cik: str | None = None
    """SEC Central Index Key, zero-padded to 10 digits."""

    isin: str | None = None
    lei: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    reporting_currency: str | None = None
    fiscal_year_end_month: int | None = Field(default=None, ge=1, le=12)
    description: Fact[str] | None = None
    sources: list[SourceRef] = Field(default_factory=list)

    @field_validator("cik")
    @classmethod
    def _pad_cik(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = value.strip().lstrip("CIK").lstrip("cik").strip()
        if not digits.isdigit():
            raise ValueError(f"CIK must be numeric, got {value!r}")
        return digits.zfill(10)

    @property
    def primary_ticker(self) -> str | None:
        for listing in self.listings:
            if listing.is_primary:
                return listing.ticker
        return self.listings[0].ticker if self.listings else None
