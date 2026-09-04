"""Normalised financial statement data.

Metrics are stored in a map rather than as fixed attributes so that new line
items can be added without breaking persisted analyses.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.facts import Fact, Period


class Metric(StrEnum):
    """Canonical metric identifiers used across all providers."""

    # Income statement
    REVENUE = "revenue"
    COST_OF_REVENUE = "cost_of_revenue"
    GROSS_PROFIT = "gross_profit"
    OPERATING_EXPENSES = "operating_expenses"
    OPERATING_INCOME = "operating_income"
    EBIT = "ebit"
    EBITDA = "ebitda"
    DEPRECIATION_AMORTIZATION = "depreciation_amortization"
    INTEREST_EXPENSE = "interest_expense"
    PRETAX_INCOME = "pretax_income"
    INCOME_TAX_EXPENSE = "income_tax_expense"
    NET_INCOME = "net_income"
    EPS_BASIC = "eps_basic"
    EPS_DILUTED = "eps_diluted"

    # Cash flow
    OPERATING_CASH_FLOW = "operating_cash_flow"
    CAPITAL_EXPENDITURE = "capital_expenditure"
    FREE_CASH_FLOW = "free_cash_flow"
    SHARE_BUYBACKS = "share_buybacks"
    DIVIDENDS_PAID = "dividends_paid"

    # Balance sheet
    CASH_AND_EQUIVALENTS = "cash_and_equivalents"
    SHORT_TERM_INVESTMENTS = "short_term_investments"
    TOTAL_CURRENT_ASSETS = "total_current_assets"
    TOTAL_ASSETS = "total_assets"
    TOTAL_CURRENT_LIABILITIES = "total_current_liabilities"
    SHORT_TERM_DEBT = "short_term_debt"
    LONG_TERM_DEBT = "long_term_debt"
    TOTAL_DEBT = "total_debt"
    NET_DEBT = "net_debt"
    TOTAL_EQUITY = "total_equity"
    WORKING_CAPITAL = "working_capital"
    INVESTED_CAPITAL = "invested_capital"

    # Share count
    SHARES_OUTSTANDING = "shares_outstanding"
    SHARES_DILUTED = "shares_diluted"

    # Derived ratios
    REVENUE_GROWTH = "revenue_growth"
    GROSS_MARGIN = "gross_margin"
    OPERATING_MARGIN = "operating_margin"
    EBITDA_MARGIN = "ebitda_margin"
    NET_MARGIN = "net_margin"
    FCF_MARGIN = "fcf_margin"
    ROE = "roe"
    ROIC = "roic"


NumericFact = Fact[float]


class FinancialSnapshot(BaseModel):
    """All known metrics for one reporting period."""

    model_config = ConfigDict(frozen=True)

    period: Period
    values: dict[Metric, NumericFact] = Field(default_factory=dict)

    def get(self, metric: Metric) -> NumericFact:
        """Return the metric, or an explicit N/A fact when absent."""
        return self.values.get(
            metric,
            Fact.not_available(period=self.period, note=f"{metric} not reported"),
        )

    def with_values(self, extra: dict[Metric, NumericFact]) -> FinancialSnapshot:
        return FinancialSnapshot(period=self.period, values={**self.values, **extra})


class FinancialHistory(BaseModel):
    """Time-ordered financial snapshots for a single company."""

    currency: str | None = None
    snapshots: list[FinancialSnapshot] = Field(default_factory=list)

    def sorted_snapshots(self) -> list[FinancialSnapshot]:
        return sorted(self.snapshots, key=lambda s: s.period.end)

    def series(self, metric: Metric) -> list[tuple[Period, NumericFact]]:
        """Chronological series for one metric, including unavailable points."""
        return [(s.period, s.get(metric)) for s in self.sorted_snapshots()]

    def available_series(self, metric: Metric) -> list[tuple[Period, float]]:
        """Chronological series restricted to periods with real data."""
        result: list[tuple[Period, float]] = []
        for period, fact in self.series(metric):
            if fact.value is not None:
                result.append((period, float(fact.value)))
        return result

    def latest(self, metric: Metric) -> NumericFact | None:
        for _period, fact in reversed(self.series(metric)):
            if fact.value is not None:
                return fact
        return None
