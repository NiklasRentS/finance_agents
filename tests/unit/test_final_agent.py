from __future__ import annotations

from app.agents.final_report import build_final_research_report
from app.services.analysis import analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


def test_final_report_contains_ordered_sections_without_recommendation() -> None:
    analysis = analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )

    report = build_final_research_report(analysis)
    assert "# Finaler Forschungsbericht" in report
    assert "## 1. Unternehmensprofil" in report
    assert "## 2. Kennzahlen" in report
    assert "## 3. Ergebnisse" in report
    assert "## 4. Risiken" in report
    assert "## 5. Wettbewerbsposition" in report
    assert "## 6. Szenarien" in report
    assert "## 7. These" in report
    assert "Kauf" not in report
    assert "Verkauf" not in report
    assert "Empfehlung" not in report
