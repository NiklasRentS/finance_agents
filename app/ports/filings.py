"""Port for regulatory filings and investor documents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.company import Company
from app.domain.facts import SourceRef


class FilingType(StrEnum):
    ANNUAL_REPORT = "10-K"
    QUARTERLY_REPORT = "10-Q"
    CURRENT_REPORT = "8-K"
    PROXY_STATEMENT = "DEF 14A"
    ANNUAL_REPORT_FOREIGN = "20-F"
    REGISTRATION = "S-1"
    OTHER = "OTHER"


class Filing(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    """Stable identifier, e.g. an SEC accession number."""

    type: FilingType
    filed_at: date
    period_end: date | None = None
    title: str | None = None
    url: str | None = None
    primary_document: str | None = None
    source: SourceRef | None = None


class FilingsProvider(ABC):
    name: str

    @abstractmethod
    def list_filings(
        self,
        company: Company,
        *,
        types: list[FilingType] | None = None,
        limit: int = 20,
    ) -> list[Filing]:
        """Return filings newest first."""

    @abstractmethod
    def get_filing_text(self, filing: Filing) -> str:
        """Return the plain text of a filing's primary document."""
