"""Controlled LLM explanation layer for deterministic investment decisions."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from app.domain.decision import (
    InvestmentDecisionBrief,
    InvestmentDecisionExplanation,
)
from app.ports.exceptions import ProviderError
from app.ports.llm import LlmClient, LlmMessage, Role

PROMPT_PATH = Path(__file__).parents[1] / "agents" / "prompts" / "investment_decision_system.md"
_FORBIDDEN = re.compile(
    r"\b(buy|sell|strong buy|strong sell|order|stop[- ]loss|kaufen|verkaufen|orderaufgabe)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?%?")


class InvestmentDecisionAgentError(RuntimeError):
    """The model response was unavailable or violated the explanation contract."""


class InvestmentDecisionAgent:
    """Ask the configured LLM to explain, never replace, a deterministic brief."""

    def __init__(self, llm: LlmClient) -> None:
        self._llm = llm

    def explain(self, brief: InvestmentDecisionBrief) -> InvestmentDecisionExplanation:
        if not self._llm.is_available():
            raise InvestmentDecisionAgentError("language model is not available")
        evidence_catalog = {
            item.evidence_id: {
                "category": item.category,
                "statement": item.statement,
                "supporting_fact_ids": item.supporting_fact_ids,
            }
            for item in brief.evidence
        }
        user_payload = {
            "authoritative_brief": brief.model_dump(mode="json"),
            "evidence_catalog": evidence_catalog,
            "rules": {
                "decision_is_authoritative": True,
                "confidence_is_authoritative": True,
                "evidence_ids_are_required": True,
            },
        }
        try:
            response = self._llm.complete(
                [
                    LlmMessage(role=Role.SYSTEM, content=PROMPT_PATH.read_text(encoding="utf-8")),
                    LlmMessage(
                        role=Role.USER,
                        content=json.dumps(user_payload, ensure_ascii=False, default=str),
                    ),
                ],
                json_schema=InvestmentDecisionExplanation.model_json_schema(),
            )
            parsed = InvestmentDecisionExplanation.model_validate_json(response.text)
        except (ProviderError, OSError, ValidationError, ValueError) as exc:
            raise InvestmentDecisionAgentError("invalid investment decision explanation") from exc

        self._validate(parsed, brief, response.model)
        return parsed.model_copy(
            update={
                "ticker": brief.ticker,
                "company_name": brief.company_name,
                "decision": brief.decision,
                "confidence": brief.confidence,
                "model_metadata": {
                    "provider": self._llm.name,
                    "model": response.model,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                },
            }
        )

    def _validate(
        self,
        explanation: InvestmentDecisionExplanation,
        brief: InvestmentDecisionBrief,
        model: str,
    ) -> None:
        if explanation.decision is not brief.decision:
            raise InvestmentDecisionAgentError("LLM attempted to override deterministic decision")
        if explanation.confidence is not brief.confidence:
            raise InvestmentDecisionAgentError("LLM attempted to override deterministic confidence")
        allowed_evidence = {item.evidence_id for item in brief.evidence}
        explanation_ids = {item.evidence_id for item in explanation.evidence}
        if not explanation_ids or not explanation_ids.issubset(allowed_evidence):
            raise InvestmentDecisionAgentError("LLM returned unsupported evidence references")
        for item in explanation.evidence:
            if not item.source_refs:
                raise InvestmentDecisionAgentError("LLM evidence has no source reference")
        text = json.dumps(explanation.model_dump(mode="json"), ensure_ascii=False)
        if _FORBIDDEN.search(text):
            raise InvestmentDecisionAgentError("LLM returned prohibited trading language")
        allowed_numbers = _numbers(json.dumps(brief.model_dump(mode="json"), ensure_ascii=False))
        if not _numbers(text).issubset(allowed_numbers):
            raise InvestmentDecisionAgentError("LLM introduced an unsupported numeric value")


def _numbers(text: str) -> set[str]:
    return {_normalise_number(token) for token in _NUMBER.findall(text)}


def _normalise_number(token: str) -> str:
    return token.replace(",", ".").replace("%", "")