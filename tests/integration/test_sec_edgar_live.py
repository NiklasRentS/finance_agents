"""Live checks against the real SEC EDGAR API.

Run explicitly with:  pytest -m integration
Requires a valid SEC_USER_AGENT in the environment.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.config.settings import get_settings
from app.domain.financials import Metric
from app.providers.sec_edgar.provider import SecEdgarFundamentalsProvider

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def provider() -> Iterator[SecEdgarFundamentalsProvider]:
    settings = get_settings()
    if "example.com" in settings.sec_user_agent:
        pytest.skip("SEC_USER_AGENT is still the placeholder")
    instance = SecEdgarFundamentalsProvider.build(settings)
    yield instance
    instance.close()


def test_resolves_apple(provider: SecEdgarFundamentalsProvider) -> None:
    company = provider.resolve_company("AAPL")
    assert company.cik == "0000320193"
    assert "Apple" in company.name


def test_fetches_ten_years_of_revenue(provider: SecEdgarFundamentalsProvider) -> None:
    company = provider.resolve_company("AAPL")
    history = provider.get_financial_history(company, max_periods=10)
    revenue = history.available_series(Metric.REVENUE)

    assert len(revenue) >= 5, "expected at least five annual revenue observations"
    assert all(value > 0 for _, value in revenue)
    for _period, fact in history.series(Metric.REVENUE):
        if fact.is_available:
            assert fact.sources, "every reported value must cite a filing"
