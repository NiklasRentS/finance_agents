"""Application service for persisted decision briefs and explanations."""

from __future__ import annotations

from typing import Any, cast

from pydantic import TypeAdapter

from app.config.settings import Settings
from app.domain.decision import InvestmentDecisionBrief, InvestmentDecisionExplanation
from app.ports.llm import LlmClient
from app.providers.ollama import OllamaClient
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.investment_decision_agent import (
    InvestmentDecisionAgent,
    InvestmentDecisionAgentError,
)

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
        llm = self._llm or OllamaClient(
            base_url=self._settings.ollama_base_url,
            model=self._settings.ollama_model,
            timeout=float(self._settings.decision_explanation_timeout_seconds),
            temperature=self._settings.llm_temperature,
        )
        should_close = self._llm is None
        try:
            return InvestmentDecisionAgent(llm).explain(brief)
        except InvestmentDecisionAgentError as exc:
            return _deterministic_explanation(brief, str(exc))
        finally:
            if should_close and hasattr(llm, "close"):
                llm.close()

    @staticmethod
    def dump(value: InvestmentDecisionBrief | InvestmentDecisionExplanation) -> dict[str, Any]:
        if isinstance(value, InvestmentDecisionBrief):
            return cast(dict[str, Any], _BRIEF.dump_python(value, mode="json"))
        return cast(dict[str, Any], _EXPLANATION.dump_python(value, mode="json"))


def _deterministic_explanation(
    brief: InvestmentDecisionBrief, reason: str
) -> InvestmentDecisionExplanation:
    """Keep Explain useful when local generation is unavailable or rejected."""
    return InvestmentDecisionExplanation(
        ticker=brief.ticker,
        company_name=brief.company_name,
        decision=brief.decision,
        confidence=brief.confidence,
        headline=f"Structured decision: {brief.decision.value}",
        summary=brief.summary,
        why_this_matters=brief.why,
        positive_factors=brief.positive_factors,
        negative_factors=brief.negative_factors,
        key_risks=brief.key_risks,
        valuation_explanation=brief.valuation_summary.interpretation,
        uncertainty=" ".join(brief.key_uncertainties) or brief.confidence_reason,
        what_to_watch=brief.monitoring_points,
        beginner_explanation=brief.beginner_explanation,
        evidence=brief.evidence,
        disclaimer=(
            "Deterministische Erklärung verwendet; lokale LLM-Erklärung war nicht "
            f"verfügbar oder wurde abgelehnt ({reason}). Keine Anlageberatung."
        ),
        model_metadata={"provider": "deterministic-fallback", "reason": reason},
    )
