"""Budget tracking for a single analysis run.

With ``max_cost_usd`` at 0 (cost tier 0) any priced call is rejected before it
is made, so the system cannot silently start spending money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


class BudgetExceededError(RuntimeError):
    """Raised before a call that would exceed the configured run budget."""


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    operation: str
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cached: bool = False


@dataclass
class CostTracker:
    """Counts requests, tokens and money spent during one run."""

    max_cost_usd: float = 0.0
    max_requests: int = 400
    records: list[UsageRecord] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_request(
        self,
        provider: str,
        operation: str,
        *,
        cost_usd: float = 0.0,
        cached: bool = False,
    ) -> UsageRecord:
        record = UsageRecord(
            provider=provider, operation=operation, cost_usd=cost_usd, cached=cached
        )
        self._append(record)
        return record

    def record_llm(
        self,
        provider: str,
        operation: str,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float = 0.0,
    ) -> UsageRecord:
        record = UsageRecord(
            provider=provider,
            operation=operation,
            cost_usd=cost_usd,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        self._append(record)
        return record

    def _append(self, record: UsageRecord) -> None:
        with self._lock:
            projected_cost = self._total_cost() + record.cost_usd
            if projected_cost > self.max_cost_usd:
                raise BudgetExceededError(
                    f"{record.provider}.{record.operation} would raise run cost to "
                    f"${projected_cost:.4f}, above the limit of ${self.max_cost_usd:.4f}."
                )
            billable = self._billable_requests()
            if not record.cached and billable + 1 > self.max_requests:
                raise BudgetExceededError(
                    f"{record.provider}.{record.operation} would exceed the limit of "
                    f"{self.max_requests} external requests per run."
                )
            self.records.append(record)

    def _total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def _billable_requests(self) -> int:
        return sum(1 for r in self.records if not r.cached)

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost()

    @property
    def external_requests(self) -> int:
        return self._billable_requests()

    @property
    def cache_hits(self) -> int:
        return sum(1 for r in self.records if r.cached)

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens_in + r.tokens_out for r in self.records)

    def summary(self) -> dict[str, float | int]:
        return {
            "total_cost_usd": round(self.total_cost_usd, 6),
            "external_requests": self.external_requests,
            "cache_hits": self.cache_hits,
            "total_tokens": self.total_tokens,
        }
