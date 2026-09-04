"""Tests for run budget enforcement."""

from __future__ import annotations

import pytest

from app.infra.cost import BudgetExceededError, CostTracker


class TestCostTierZero:
    def test_free_requests_are_allowed(self) -> None:
        tracker = CostTracker(max_cost_usd=0.0, max_requests=10)
        tracker.record_request("sec_edgar", "companyfacts")
        assert tracker.total_cost_usd == 0.0
        assert tracker.external_requests == 1

    def test_any_priced_call_is_rejected_at_tier_zero(self) -> None:
        tracker = CostTracker(max_cost_usd=0.0, max_requests=10)
        with pytest.raises(BudgetExceededError, match="above the limit"):
            tracker.record_request("paid_provider", "fundamentals", cost_usd=0.01)
        assert tracker.records == []

    def test_local_llm_usage_is_free(self) -> None:
        tracker = CostTracker(max_cost_usd=0.0, max_requests=10)
        tracker.record_llm("ollama", "summarise", tokens_in=1200, tokens_out=300)
        assert tracker.total_tokens == 1500
        assert tracker.total_cost_usd == 0.0


class TestCostLimits:
    def test_cost_accumulates_until_limit(self) -> None:
        tracker = CostTracker(max_cost_usd=0.05, max_requests=100)
        tracker.record_request("p", "op", cost_usd=0.03)
        tracker.record_request("p", "op", cost_usd=0.02)
        assert tracker.total_cost_usd == pytest.approx(0.05)
        with pytest.raises(BudgetExceededError):
            tracker.record_request("p", "op", cost_usd=0.01)

    def test_request_count_limit_is_enforced(self) -> None:
        tracker = CostTracker(max_cost_usd=0.0, max_requests=2)
        tracker.record_request("p", "op")
        tracker.record_request("p", "op")
        with pytest.raises(BudgetExceededError, match="external requests"):
            tracker.record_request("p", "op")

    def test_cache_hits_do_not_count_against_request_limit(self) -> None:
        tracker = CostTracker(max_cost_usd=0.0, max_requests=1)
        tracker.record_request("p", "op")
        for _ in range(5):
            tracker.record_request("p", "op", cached=True)
        assert tracker.external_requests == 1
        assert tracker.cache_hits == 5

    def test_summary_reports_all_counters(self) -> None:
        tracker = CostTracker(max_cost_usd=1.0, max_requests=10)
        tracker.record_request("p", "op", cost_usd=0.25)
        tracker.record_request("p", "op", cached=True)
        tracker.record_llm("ollama", "draft", tokens_in=10, tokens_out=5)
        assert tracker.summary() == {
            "total_cost_usd": 0.25,
            "external_requests": 2,
            "cache_hits": 1,
            "total_tokens": 15,
        }
