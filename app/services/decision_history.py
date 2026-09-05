"""Deterministic decision history and watchlist attention services."""

from __future__ import annotations

from app.domain.decision import DecisionCategory, InvestmentDecisionBrief
from app.domain.decision_history import (
    DecisionHistory,
    WatchlistAttentionItem,
    WatchlistAttentionResponse,
)
from app.repositories.analysis_store import SqlAnalysisStore, StoredRun


class DecisionHistoryService:
    def __init__(self, store: SqlAnalysisStore) -> None:
        self._store = store

    def compare_latest(self, ticker: str) -> DecisionHistory | None:
        runs = self._runs_with_briefs(ticker, limit=2)
        if not runs:
            return None
        current_run, current_brief = runs[0]
        previous_run, previous_brief = runs[1] if len(runs) > 1 else (None, None)
        return compare_briefs(
            current_run=current_run,
            current_brief=current_brief,
            previous_run=previous_run,
            previous_brief=previous_brief,
        )

    def watchlist_attention(self, *, limit: int = 3) -> WatchlistAttentionResponse:
        items: list[WatchlistAttentionItem] = []
        for watchlist_item in self._store.list_watchlist():
            ticker = str(watchlist_item["ticker"])
            history = self.compare_latest(ticker)
            if history is None:
                continue
            changed_fields = history.key_changes
            priority = _priority(history)
            items.append(
                WatchlistAttentionItem(
                    ticker=ticker,
                    company_name=str(watchlist_item["company_name"]),
                    priority=priority,
                    reason=history.important_change,
                    current_decision=history.current_decision,
                    previous_decision=history.previous_decision,
                    latest_run_id=history.current_run_id,
                    changed_fields=changed_fields,
                    generated_at=history.current_generated_at,
                )
            )
        ranked = sorted(items, key=lambda item: (-item.priority, item.ticker))[:limit]
        return WatchlistAttentionResponse(
            items=ranked,
            message=None if ranked else "Keine wesentlichen Änderungen seit der letzten Analyse.",
        )

    def _runs_with_briefs(
        self, ticker: str, *, limit: int
    ) -> list[tuple[StoredRun, InvestmentDecisionBrief]]:
        result: list[tuple[StoredRun, InvestmentDecisionBrief]] = []
        for summary in self._store.list_runs(ticker=ticker, limit=limit):
            run = self._store.load_run_document(summary.id)
            if run is None or run.decision_brief is None:
                continue
            result.append((run, InvestmentDecisionBrief.model_validate(run.decision_brief)))
        return result


def compare_briefs(
    *,
    current_run: StoredRun,
    current_brief: InvestmentDecisionBrief,
    previous_run: StoredRun | None,
    previous_brief: InvestmentDecisionBrief | None,
) -> DecisionHistory:
    if previous_run is None or previous_brief is None:
        return DecisionHistory(
            ticker=current_run.ticker,
            current_run_id=str(current_run.id),
            current_generated_at=current_run.generated_at,
            current_decision=current_brief.decision,
            current_confidence=current_brief.confidence,
            important_change="Keine vorherige Decision-Analyse zum Vergleich vorhanden.",
        )

    changes: list[str] = []
    valuation_change = _change_label(
        current_brief.valuation_summary.model_dump(mode="json"),
        previous_brief.valuation_summary.model_dump(mode="json"),
        "Bewertung",
        changes,
    )
    risk_change = _change_label(
        current_brief.key_risks,
        previous_brief.key_risks,
        "Risiken",
        changes,
    )
    thesis_change = _change_label(
        current_brief.investment_thesis,
        previous_brief.investment_thesis,
        "These",
        changes,
    )
    scenario_change = _change_label(
        current_brief.monitoring_points,
        previous_brief.monitoring_points,
        "Monitoring-Punkte",
        changes,
    )
    if current_brief.decision != previous_brief.decision:
        changes.append(
            f"Decision: {previous_brief.decision.value} -> {current_brief.decision.value}"
        )
    if current_brief.confidence != previous_brief.confidence:
        changes.append(
            f"Confidence: {previous_brief.confidence.value} -> {current_brief.confidence.value}"
        )

    important = changes[0] if changes else "Keine wesentliche strukturierte Veränderung erkannt."
    return DecisionHistory(
        ticker=current_run.ticker,
        current_run_id=str(current_run.id),
        current_generated_at=current_run.generated_at,
        current_decision=current_brief.decision,
        current_confidence=current_brief.confidence,
        previous_run_id=str(previous_run.id),
        previous_generated_at=previous_run.generated_at,
        previous_decision=previous_brief.decision,
        previous_confidence=previous_brief.confidence,
        decision_changed=current_brief.decision != previous_brief.decision,
        key_changes=changes,
        valuation_change=valuation_change,
        risk_change=risk_change,
        thesis_change=thesis_change,
        scenario_change=scenario_change,
        important_change=important,
        evidence=current_brief.evidence,
    )


def _change_label(current: object, previous: object, label: str, changes: list[str]) -> str:
    if current == previous:
        return "unchanged"
    changes.append(f"{label} hat sich seit der vorherigen Analyse verändert.")
    return "changed"


def _priority(history: DecisionHistory) -> int:
    score = 0
    if history.decision_changed:
        score += 5
    if history.current_decision in {
        DecisionCategory.CAUTION,
        DecisionCategory.REVIEW_THESIS,
    }:
        score += 3
    if history.current_decision is DecisionCategory.INSUFFICIENT_DATA:
        score += 2
    score += min(3, len(history.key_changes))
    return score
