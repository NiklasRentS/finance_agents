"""Port for persisting finished analysis runs.

Storing a run is what later makes history, diffs and alerts possible: a value
can only be called "changed" if the previous value is still on record.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imported for typing only, keeps the port free of service imports
    from app.domain.financials import FinancialHistory
    from app.services.analysis import CompanyAnalysis


@dataclass(frozen=True)
class RunSummary:
    """Enough about a stored run to list and identify it without loading it."""

    id: uuid.UUID
    ticker: str
    company_name: str
    generated_at: datetime
    currency: str | None = None
    period_label: str | None = None
    value_per_share: float | None = None


class AnalysisStore(ABC):
    """Repository for completed runs."""

    @abstractmethod
    def save_run(
        self, analysis: CompanyAnalysis, *, report_markdown: str | None = None
    ) -> uuid.UUID:
        """Persist one run and return its identifier."""

    @abstractmethod
    def list_runs(self, *, ticker: str | None = None, limit: int = 20) -> list[RunSummary]:
        """Return stored runs, most recent first."""

    @abstractmethod
    def load_history(self, run_id: uuid.UUID) -> FinancialHistory | None:
        """Return the financial facts of a run, or ``None`` if it is unknown."""

    @abstractmethod
    def load_report(self, run_id: uuid.UUID) -> str | None:
        """Return the stored Markdown report, or ``None`` if none was saved."""

    @abstractmethod
    def add_watchlist_item(
        self, *, ticker: str, company_name: str, notes: str | None = None
    ) -> dict[str, str | None]:
        """Add or replace an item in the watchlist."""

    @abstractmethod
    def list_watchlist(self) -> list[dict[str, str | None]]:
        """Return the current watchlist in reverse-chronological order."""
