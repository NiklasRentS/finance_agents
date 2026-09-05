"""Application service for persisted decision briefs and explanations."""

from __future__ import annotations

from typing import Any, cast

from pydantic import TypeAdapter

from app.config.settings import Settings
from app.domain.decision import InvestmentDecisionBrief, InvestmentDecisionExplanation
from app.ports.llm import LlmClient
from app.providers.ollama import OllamaClient
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.investment_decision_agent import InvestmentDecisionAgent

_BRIEF = TypeAdapter(InvestmentDecisionBrief)
_EXPLANATION = TypeAdapter(InvestmentDecisionExplanation)


class DecisionApiService:
    """Keep API adapters thin around persisted briefs and the LLM explanation port."""

    def __init__(
        self,
        store: SqlAnalysisStore,
        settings: Settings,
        *,
        llm: LlmClient | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._llm = llm

    def latest_brief(self, ticker: str) -> InvestmentDecisionBrief | None:
        run = self._store.load_latest_run(ticker)
        if run is None or run.decision_brief is None:
            return None
        return _BRIEF.validate_python(run.decision_brief)

    def explain_latest(self, ticker: str) -> InvestmentDecisionExplanation:
        brief = self.latest_brief(ticker)
        if brief is None:
            raise LookupError("no persisted decision brief for ticker")
        llm = self._llm or OllamaClient.build(self._settings)
        should_close = self._llm is None
        try:
            return InvestmentDecisionAgent(llm).explain(brief)
        finally:
            if should_close and hasattr(llm, "close"):
                llm.close()

    @staticmethod
    def dump(value: InvestmentDecisionBrief | InvestmentDecisionExplanation) -> dict[str, Any]:
        if isinstance(value, InvestmentDecisionBrief):
            return cast(dict[str, Any], _BRIEF.dump_python(value, mode="json"))
        return cast(dict[str, Any], _EXPLANATION.dump_python(value, mode="json"))
