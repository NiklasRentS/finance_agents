from __future__ import annotations

from app.agents.competitive import build_competitive_summary
from app.agents.risk import build_risk_signals
from app.agents.scenarios import build_scenario_outcomes, build_thesis_statement
from app.services.analysis import analyse_company
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


def _analysis():
    return analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )


def test_risk_signals_are_generated() -> None:
    signals = build_risk_signals(_analysis())
    assert signals
    assert all(0 <= signal.score <= 100 for signal in signals)
    assert any(signal.summary for signal in signals)


def test_competitive_summary_is_generated() -> None:
    summary = build_competitive_summary(_analysis())
    assert summary
    assert 0 <= summary.score <= 100
    assert summary.summary


def test_scenarios_and_thesis_are_generated() -> None:
    scenarios = build_scenario_outcomes(_analysis())
    assert scenarios
    assert all(0 <= scenario.probability <= 1 for scenario in scenarios)
    thesis = build_thesis_statement(_analysis())
    assert thesis
    assert "".join(scenario.name for scenario in scenarios)
