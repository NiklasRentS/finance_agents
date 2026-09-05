from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.decision import DecisionCategory, InvestmentDecisionExplanation
from app.ports.llm import LlmClient, LlmMessage, LlmResponse
from app.services.analysis import analyse_company
from app.services.decision_engine import build_decision_input, evaluate_decision
from app.services.investment_decision_agent import (
    InvestmentDecisionAgent,
    InvestmentDecisionAgentError,
)
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


class FakeDecisionLlm(LlmClient):
    name = "fake_decision_llm"

    def __init__(self, payload: dict[str, Any] | str, *, available: bool = True) -> None:
        self.payload = payload
        self.available = available
        self.messages: list[LlmMessage] = []
        self.schema: dict[str, Any] | None = None

    def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        self.messages = messages
        self.schema = json_schema
        if isinstance(self.payload, str):
            text = self.payload
        else:
            text = json.dumps(self.payload, ensure_ascii=False)
        return LlmResponse(text=text, model=self.name, tokens_in=10, tokens_out=20)

    def is_available(self) -> bool:
        return self.available


def brief():
    analysis = analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )
    return evaluate_decision(build_decision_input(analysis, analysis_run_id="run-1"))


def valid_payload() -> dict[str, Any]:
    deterministic = brief()
    evidence = [item.model_dump(mode="json") for item in deterministic.evidence]
    return {
        "ticker": deterministic.ticker,
        "company_name": deterministic.company_name,
        "decision": deterministic.decision.value,
        "confidence": deterministic.confidence.value,
        "headline": "Structured research overview",
        "summary": "The available evidence supports a cautious research framing.",
        "why_this_matters": "The decision reflects the quality of the supplied evidence.",
        "positive_factors": ["Reported operating data is available."],
        "negative_factors": ["Valuation depends on model assumptions."],
        "key_risks": ["The supplied risk signals should be monitored."],
        "valuation_explanation": "The DCF is a model dependent on explicit assumptions.",
        "uncertainty": "The result is not a forecast or guarantee.",
        "what_to_watch": ["Revenue, margins, and cash flow in the next report."],
        "beginner_explanation": {
            "explanation": "This summarizes the existing structured analysis.",
            "why_it_matters": "It helps explain the evidence without adding facts.",
            "key_terms": {"DCF": "A model that discounts expected cash flows."},
        },
        "evidence": evidence,
        "disclaimer": "Research context only; the final decision remains with the user.",
    }


def test_valid_structured_explanation_is_accepted() -> None:
    llm = FakeDecisionLlm(valid_payload())

    result = InvestmentDecisionAgent(llm).explain(brief())

    assert isinstance(result, InvestmentDecisionExplanation)
    assert result.decision is brief().decision
    assert result.confidence is brief().confidence
    assert result.evidence
    assert llm.schema is not None
    assert "investment research explanation assistant" in llm.messages[0].content


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(InvestmentDecisionAgentError, match="invalid"):
        InvestmentDecisionAgent(FakeDecisionLlm("not json")).explain(brief())


def test_invalid_pydantic_response_is_rejected() -> None:
    payload = valid_payload()
    del payload["headline"]

    with pytest.raises(InvestmentDecisionAgentError, match="invalid"):
        InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(brief())


def test_unknown_evidence_id_is_rejected() -> None:
    payload = valid_payload()
    payload["evidence"][0]["evidence_id"] = "unknown-evidence"

    with pytest.raises(InvestmentDecisionAgentError, match="unsupported evidence"):
        InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(brief())


def test_decision_override_is_rejected() -> None:
    payload = valid_payload()
    payload["decision"] = "ATTRACTIVE" if payload["decision"] != "ATTRACTIVE" else "WATCH"

    with pytest.raises(InvestmentDecisionAgentError, match="override deterministic decision"):
        InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(brief())


def test_confidence_override_is_rejected() -> None:
    payload = valid_payload()
    payload["confidence"] = "HIGH" if payload["confidence"] != "HIGH" else "LOW"

    with pytest.raises(InvestmentDecisionAgentError, match="override deterministic confidence"):
        InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(brief())


def test_hallucinated_number_is_rejected() -> None:
    payload = valid_payload()
    payload["summary"] = "The company has a 987654321% margin."

    with pytest.raises(InvestmentDecisionAgentError, match="numeric value"):
        InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(brief())


def test_buy_sell_language_is_rejected() -> None:
    payload = valid_payload()
    payload["summary"] = "BUY this stock immediately."

    with pytest.raises(InvestmentDecisionAgentError, match="trading language"):
        InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(brief())


def test_unavailable_llm_is_rejected_without_fallback_generation() -> None:
    with pytest.raises(InvestmentDecisionAgentError, match="not available"):
        InvestmentDecisionAgent(FakeDecisionLlm(valid_payload(), available=False)).explain(brief())


def test_insufficient_data_decision_is_preserved() -> None:
    deterministic = brief().model_copy(update={"decision": DecisionCategory.INSUFFICIENT_DATA})
    payload = valid_payload()
    payload["decision"] = "INSUFFICIENT_DATA"
    payload["confidence"] = deterministic.confidence.value
    payload["summary"] = "Central data is missing, so no stronger conclusion is supported."

    result = InvestmentDecisionAgent(FakeDecisionLlm(payload)).explain(deterministic)

    assert result.decision.value == "INSUFFICIENT_DATA"
