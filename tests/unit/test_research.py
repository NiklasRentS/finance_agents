"""Tests for the research agent and the Ollama adapter.

The agent's contract is negative: it must drop anything the facts do not carry.
Most tests therefore assert what does *not* end up in the report.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.agents.research import ResearchNotes, build_fact_cards, run_research
from app.ports.exceptions import ProviderUnavailableError
from app.ports.llm import LlmClient, LlmMessage, LlmResponse, Role
from app.providers.ollama import OllamaClient
from app.reporting.markdown import render_markdown
from app.services.analysis import CompanyAnalysis, analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData

BASE_URL = "http://llm.test:11434"


def _analysis() -> CompanyAnalysis:
    return analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )


class FakeLlm(LlmClient):
    """Returns a canned payload and records what it was asked."""

    name = "fake_llm"

    def __init__(self, payload: Any, *, available: bool = True, fail: bool = False) -> None:
        self._payload = payload
        self._available = available
        self._fail = fail
        self.messages: list[LlmMessage] = []
        self.json_schema: dict[str, Any] | None = None

    def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        if self._fail:
            raise ProviderUnavailableError(self.name, "offline")
        self.messages = messages
        self.json_schema = json_schema
        text = self._payload if isinstance(self._payload, str) else json.dumps(self._payload)
        return LlmResponse(text=text, model=self.name, tokens_in=10, tokens_out=20)

    def is_available(self) -> bool:
        return self._available


def _payload(*findings: dict[str, Any], questions: list[str] | None = None) -> dict[str, Any]:
    return {"findings": list(findings), "open_questions": questions or []}


class TestFactCards:
    def test_cards_carry_sources_and_numbers(self) -> None:
        cards = build_fact_cards(_analysis())
        assert cards
        assert cards[0].id == "F1"
        assert all(card.sources for card in cards)
        assert "Umsatz" in cards[0].label

    def test_prompt_only_contains_supplied_facts(self) -> None:
        analysis = _analysis()
        llm = FakeLlm(_payload())
        run_research(analysis, llm)
        prompt = llm.messages[-1].content
        for card in build_fact_cards(analysis):
            assert card.render() in prompt
        assert llm.json_schema is not None


class TestValidation:
    def test_statement_with_known_numbers_is_kept(self) -> None:
        analysis = _analysis()
        card = build_fact_cards(analysis)[0]
        finding = {
            "category": "OBSERVATION",
            "statement": f"Der Umsatz liegt bei {card.value}.",
            "fact_ids": [card.id],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        assert len(notes.notes) == 1
        assert notes.notes[0].sources == card.sources
        assert notes.rejected == 0

    def test_inline_citation_is_not_read_as_a_number(self) -> None:
        # Models repeat the citation in the sentence: "... (F5)". Our own
        # numbering must not count as an unsupported figure.
        analysis = _analysis()
        card = next(c for c in build_fact_cards(analysis) if c.id == "F5")
        finding = {
            "category": "OBSERVATION",
            "statement": f"Der Jahresueberschuss liegt bei {card.value} (F5).",
            "fact_ids": [card.id],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        assert len(notes.notes) == 1

    def test_invented_number_is_rejected(self) -> None:
        analysis = _analysis()
        card = build_fact_cards(analysis)[0]
        finding = {
            "category": "OBSERVATION",
            "statement": "Der Marktanteil betraegt 37,4 Prozent.",
            "fact_ids": [card.id],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        assert notes.notes == ()
        assert notes.rejected == 1
        assert "verworfen" in notes.warnings[0]

    def test_unknown_fact_id_is_rejected(self) -> None:
        analysis = _analysis()
        finding = {
            "category": "RISK",
            "statement": "Die Verschuldung steigt.",
            "fact_ids": ["F999"],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        assert notes.notes == ()
        assert notes.rejected == 1

    def test_statement_without_citation_is_rejected(self) -> None:
        finding = {"category": "TREND", "statement": "Das Geschaeft waechst.", "fact_ids": []}
        notes = run_research(_analysis(), FakeLlm(_payload(finding)))
        assert notes.notes == ()

    def test_partially_supported_citation_is_rejected(self) -> None:
        analysis = _analysis()
        card = build_fact_cards(analysis)[0]
        finding = {
            "category": "OBSERVATION",
            "statement": "Umsatz und Marge entwickeln sich stabil.",
            "fact_ids": [card.id, "F404"],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        assert notes.notes == ()
        assert notes.rejected == 1

    def test_number_limit_is_per_cited_fact(self) -> None:
        analysis = _analysis()
        cards = build_fact_cards(analysis)
        borrowed = next(card for card in cards if "Ergebnis je Aktie" in card.label)
        finding = {
            "category": "OBSERVATION",
            "statement": f"Der Umsatz liegt bei {borrowed.value}.",
            "fact_ids": [cards[0].id],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        assert notes.notes == ()

    def test_open_questions_survive_without_citation(self) -> None:
        notes = run_research(
            _analysis(), FakeLlm(_payload(questions=["Wie ist der Umsatz nach Regionen verteilt?"]))
        )
        assert notes.open_questions == ("Wie ist der Umsatz nach Regionen verteilt?",)

    def test_note_count_is_capped(self) -> None:
        analysis = _analysis()
        cards = build_fact_cards(analysis)[:5]
        findings = [
            {
                "category": "OBSERVATION",
                "statement": f"{card.label} betraegt {card.value}.",
                "fact_ids": [card.id],
            }
            for card in cards
        ]
        notes = run_research(analysis, FakeLlm(_payload(*findings)), max_notes=2)
        assert len(notes.notes) == 2


class TestFailureModes:
    def test_unavailable_model_yields_a_warning_not_an_error(self) -> None:
        notes = run_research(_analysis(), FakeLlm(_payload(), available=False))
        assert notes.notes == ()
        assert "nicht erreichbar" in notes.warnings[0]

    def test_provider_error_is_contained(self) -> None:
        notes = run_research(_analysis(), FakeLlm(_payload(), fail=True))
        assert notes.notes == ()
        assert notes.warnings

    def test_unparsable_answer_is_discarded(self) -> None:
        notes = run_research(_analysis(), FakeLlm("Ich bin ein Sprachmodell, kein JSON."))
        assert notes.notes == ()
        assert "nicht auswertbar" in notes.warnings[0]


class TestReportSection:
    def test_section_is_absent_without_research(self) -> None:
        assert "Qualitative Einordnung" not in render_markdown(_analysis())

    def test_notes_are_rendered_with_source_markers(self) -> None:
        analysis = _analysis()
        card = build_fact_cards(analysis)[0]
        finding = {
            "category": "TREND",
            "statement": f"Der Umsatz liegt bei {card.value}.",
            "fact_ids": [card.id],
        }
        notes = run_research(analysis, FakeLlm(_payload(finding)))
        report = render_markdown(analysis, notes)
        assert "## Qualitative Einordnung" in report
        assert "**Entwicklung:**" in report
        assert "[1]" in report

    def test_empty_result_is_stated_explicitly(self) -> None:
        analysis = _analysis()
        report = render_markdown(analysis, ResearchNotes(model="fake"))
        assert "Keine belegbaren Aussagen erzeugt." in report


class TestOllamaClient:
    def _client(self) -> OllamaClient:
        return OllamaClient(
            base_url=BASE_URL, model="qwen2.5:7b-instruct", timeout=5.0, temperature=0.1
        )

    @respx.mock
    def test_chat_request_is_not_streamed_and_carries_the_schema(self) -> None:
        route = respx.post(f"{BASE_URL}/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "model": "qwen2.5:7b-instruct",
                    "message": {"role": "assistant", "content": "{}"},
                    "prompt_eval_count": 42,
                    "eval_count": 7,
                },
            )
        )
        client = self._client()
        response = client.complete(
            [LlmMessage(role=Role.USER, content="Hallo")], json_schema={"type": "object"}
        )
        body = json.loads(route.calls[0].request.content)
        assert body["stream"] is False
        assert body["format"] == {"type": "object"}
        assert body["options"]["temperature"] == 0.1
        assert response.text == "{}"
        assert (response.tokens_in, response.tokens_out) == (42, 7)
        client.close()

    @respx.mock
    def test_http_error_becomes_a_provider_error(self) -> None:
        respx.post(f"{BASE_URL}/api/chat").mock(return_value=httpx.Response(500))
        client = self._client()
        with pytest.raises(ProviderUnavailableError):
            client.complete([LlmMessage(role=Role.USER, content="Hallo")])
        client.close()

    @respx.mock
    def test_availability_requires_the_configured_model(self) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})
        )
        client = self._client()
        assert client.is_available() is False
        client.close()

    @respx.mock
    def test_availability_is_true_when_the_model_is_installed(self) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen2.5:7b-instruct"}]})
        )
        client = self._client()
        assert client.is_available() is True
        client.close()

    @respx.mock
    def test_unreachable_server_is_not_available(self) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
        client = self._client()
        assert client.is_available() is False
        client.close()
