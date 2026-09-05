from __future__ import annotations

import pytest

from app.agents.earnings import build_earnings_delta
from app.domain.financials import Metric
from app.services.analysis import analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


def test_earnings_delta_uses_previous_period() -> None:
    analysis = analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )

    deltas = build_earnings_delta(analysis)
    assert deltas
    revenue = next(item for item in deltas if item.metric == Metric.REVENUE)
    assert revenue.previous is not None
    assert revenue.current is not None
    assert revenue.delta > 0
    assert revenue.pct_change == pytest.approx(0.07407407407407407)


def test_earnings_delta_ignores_missing_previous_data() -> None:
    analysis = analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(years=(2025,)),
        market_data=ConfigurableFakeMarketData(),
    )

    assert build_earnings_delta(analysis) == []
