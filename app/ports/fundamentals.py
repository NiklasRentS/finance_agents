"""Port for company identity and financial statement data."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.company import Company
from app.domain.facts import PeriodType
from app.domain.financials import FinancialHistory


class FundamentalsProvider(ABC):
    name: str

    @abstractmethod
    def resolve_company(self, identifier: str) -> Company:
        """Resolve a ticker, name or CIK into a company identity.

        Raises:
            CompanyNotFoundError: if the identifier cannot be resolved.
        """

    @abstractmethod
    def get_financial_history(
        self,
        company: Company,
        *,
        period_type: PeriodType = PeriodType.FISCAL_YEAR,
        max_periods: int = 10,
    ) -> FinancialHistory:
        """Return normalised statements, most recent ``max_periods`` periods.

        Periods without data must be omitted or carry N/A facts. Implementations
        must never interpolate or estimate missing line items.
        """
