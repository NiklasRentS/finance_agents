from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings
from app.ports.llm import LlmClient, LlmMessage, LlmResponse
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.analysis import analyse_company
from app.services.decision_api import DecisionApiService
from app.services.investment_decision_agent import InvestmentDecisionAgentError
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


class FakeLlm(LlmClient):
    name = "fake_api_llm"

    def __init__(self, payload: dict[str, Any], *, available: bool = True) -> None:
        self.payload = payload
        self.available = available

    def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        return LlmResponse(text=json.dumps(self.payload), model=self.name)

    def is_available(self) -> bool:
        return self.available


def make_store() -> SqlAnalysisStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store = SqlAnalysisStore(engine)
    store.create_schema()
    store.save_run(
        analyse_company(
            "EXMP",
            fundamentals=CompleteFakeFundamentals(),
            market_data=ConfigurableFakeMarketData(),
        )
    )
    return store


def explanation_payload(brief: Any) -> dict[str, Any]:
    return {
        "ticker": brief.ticker,
        "company_name": brief.company_name,
        "decision": brief.decision.value,
        "confidence": brief.confidence.value,
        "headline": "Research explanation",
        "summary": "The supplied evidence is summarized without adding facts.",
        "why_this_matters": "The decision reflects evidence quality.",
        "positive_factors": ["Reported facts are available."],
        "negative_factors": ["The model remains assumption-dependent."],
        "key_risks": ["Existing risk signals require monitoring."],
        "valuation_explanation": "The valuation uses the persisted deterministic model.",
        "uncertainty": "The result is not a forecast.",
        "what_to_watch": ["The next reported operating period."],
        "beginner_explanation": {
            "explanation": "This explains the existing analysis.",
            "why_it_matters": "It does not add new financial facts.",
            "key_terms": {"DCF": "A cash flow valuation model."},
        },
        "evidence": [item.model_dump(mode="json") for item in brief.evidence],
        "disclaimer": "Research context only; the final decision remains with the user.",
    }


def test_service_loads_persisted_brief_from_existing_run() -> None:
    store = make_store()
    service = DecisionApiService(store, Settings())

    brief = service.latest_brief("EXMP")

    assert brief is not None
    assert brief.analysis_run_id
    store.close()


def test_service_explains_using_existing_llm_port() -> None:
    store = make_store()
    service = DecisionApiService(store, Settings())
    brief = service.latest_brief("EXMP")
    assert brief is not None
    service = DecisionApiService(store, Settings(), llm=FakeLlm(explanation_payload(brief)))

    explanation = service.explain_latest("EXMP")

    assert explanation.decision is brief.decision
    assert explanation.model_metadata["provider"] == "fake_api_llm"
    store.close()


def test_service_rejects_unavailable_llm() -> None:
    store = make_store()
    service = DecisionApiService(store, Settings(), llm=FakeLlm({}, available=False))

    with pytest.raises(InvestmentDecisionAgentError):
        service.explain_latest("EXMP")
    store.close()
