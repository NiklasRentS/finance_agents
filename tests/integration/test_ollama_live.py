"""Live tests against a locally running Ollama server.

Run with ``pytest -m integration``. Skipped when the model is not installed.
"""

from __future__ import annotations

import pytest

from app.agents.research import ResearchOutput, build_fact_cards, run_research
from app.config.settings import get_settings
from app.ports.llm import LlmMessage, Role
from app.providers.ollama import OllamaClient
from app.services.analysis import analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> OllamaClient:
    llm = OllamaClient.build(get_settings())
    if not llm.is_available():
        llm.close()
        pytest.skip("Ollama oder das konfigurierte Modell ist nicht verfuegbar.")
    return llm


def test_model_answers_with_schema_conform_json(client: OllamaClient) -> None:
    response = client.complete(
        [
            LlmMessage(
                role=Role.USER,
                content=("Gib ein leeres Ergebnis zurueck: keine findings, keine open_questions."),
            )
        ],
        json_schema=ResearchOutput.model_json_schema(),
    )
    parsed = ResearchOutput.model_validate_json(response.text)
    assert isinstance(parsed.findings, list)
    assert response.tokens_out > 0


def test_research_notes_only_cite_supplied_facts(client: OllamaClient) -> None:
    analysis = analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )
    known = {card.id for card in build_fact_cards(analysis)}
    notes = run_research(analysis, client, max_notes=3)

    assert notes.model
    for note in notes.notes:
        assert set(note.fact_ids) <= known
        assert note.sources
