"""Mapping from our canonical metrics to US-GAAP XBRL tags.

Tags are listed in priority order: the first tag present in a company's
``companyfacts`` payload wins. Filers use different tags for the same concept,
so several candidates per metric are the norm rather than the exception.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.financials import Metric

UNIT_MONEY = "USD"
UNIT_SHARES = "shares"
UNIT_PER_SHARE = "USD/shares"


@dataclass(frozen=True)
class TagSpec:
    taxonomy: str
    tags: tuple[str, ...]
    unit: str
    instant: bool
    """True for balance-sheet items measured at a point in time."""


METRIC_TAGS: dict[Metric, TagSpec] = {
    Metric.REVENUE: TagSpec(
        "us-gaap",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.COST_OF_REVENUE: TagSpec(
        "us-gaap",
        ("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfServices"),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.GROSS_PROFIT: TagSpec("us-gaap", ("GrossProfit",), UNIT_MONEY, instant=False),
    Metric.OPERATING_EXPENSES: TagSpec(
        "us-gaap", ("OperatingExpenses", "CostsAndExpenses"), UNIT_MONEY, instant=False
    ),
    Metric.OPERATING_INCOME: TagSpec(
        "us-gaap", ("OperatingIncomeLoss",), UNIT_MONEY, instant=False
    ),
    Metric.DEPRECIATION_AMORTIZATION: TagSpec(
        "us-gaap",
        (
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
        ),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.INTEREST_EXPENSE: TagSpec(
        "us-gaap",
        ("InterestExpense", "InterestExpenseDebt", "InterestIncomeExpenseNet"),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.PRETAX_INCOME: TagSpec(
        "us-gaap",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.INCOME_TAX_EXPENSE: TagSpec(
        "us-gaap", ("IncomeTaxExpenseBenefit",), UNIT_MONEY, instant=False
    ),
    Metric.NET_INCOME: TagSpec(
        "us-gaap", ("NetIncomeLoss", "ProfitLoss"), UNIT_MONEY, instant=False
    ),
    Metric.EPS_BASIC: TagSpec("us-gaap", ("EarningsPerShareBasic",), UNIT_PER_SHARE, instant=False),
    Metric.EPS_DILUTED: TagSpec(
        "us-gaap", ("EarningsPerShareDiluted",), UNIT_PER_SHARE, instant=False
    ),
    Metric.OPERATING_CASH_FLOW: TagSpec(
        "us-gaap",
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.CAPITAL_EXPENDITURE: TagSpec(
        "us-gaap",
        (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.SHARE_BUYBACKS: TagSpec(
        "us-gaap", ("PaymentsForRepurchaseOfCommonStock",), UNIT_MONEY, instant=False
    ),
    Metric.DIVIDENDS_PAID: TagSpec(
        "us-gaap",
        ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
        UNIT_MONEY,
        instant=False,
    ),
    Metric.SHARES_DILUTED: TagSpec(
        "us-gaap",
        ("WeightedAverageNumberOfDilutedSharesOutstanding",),
        UNIT_SHARES,
        instant=False,
    ),
    Metric.CASH_AND_EQUIVALENTS: TagSpec(
        "us-gaap",
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        UNIT_MONEY,
        instant=True,
    ),
    Metric.SHORT_TERM_INVESTMENTS: TagSpec(
        "us-gaap",
        ("MarketableSecuritiesCurrent", "ShortTermInvestments"),
        UNIT_MONEY,
        instant=True,
    ),
    Metric.TOTAL_CURRENT_ASSETS: TagSpec("us-gaap", ("AssetsCurrent",), UNIT_MONEY, instant=True),
    Metric.TOTAL_ASSETS: TagSpec("us-gaap", ("Assets",), UNIT_MONEY, instant=True),
    Metric.TOTAL_CURRENT_LIABILITIES: TagSpec(
        "us-gaap", ("LiabilitiesCurrent",), UNIT_MONEY, instant=True
    ),
    Metric.SHORT_TERM_DEBT: TagSpec(
        "us-gaap", ("DebtCurrent", "LongTermDebtCurrent"), UNIT_MONEY, instant=True
    ),
    Metric.LONG_TERM_DEBT: TagSpec(
        "us-gaap",
        ("LongTermDebtNoncurrent", "LongTermDebt"),
        UNIT_MONEY,
        instant=True,
    ),
    Metric.TOTAL_EQUITY: TagSpec(
        "us-gaap",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        UNIT_MONEY,
        instant=True,
    ),
    Metric.SHARES_OUTSTANDING: TagSpec(
        "dei", ("EntityCommonStockSharesOutstanding",), UNIT_SHARES, instant=True
    ),
}
