"""Tests for the command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from app import cli
from app.ports.exceptions import CompanyNotFoundError
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData

runner = CliRunner()


@pytest.fixture(autouse=True)
def stub_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the CLI offline: no test may reach the network."""
    monkeypatch.setattr(
        "app.cli.SecEdgarFundamentalsProvider.build",
        classmethod(lambda cls, *args, **kwargs: CompleteFakeFundamentals()),
    )
    monkeypatch.setattr(
        "app.cli.YahooFinanceMarketDataProvider.build",
        classmethod(lambda cls, *args, **kwargs: ConfigurableFakeMarketData()),
    )


class TestAnalyzeCommand:
    def test_report_is_printed_to_stdout(self) -> None:
        result = runner.invoke(cli.app, ["analyze", "EXMP"])
        assert result.exit_code == 0
        assert "# Fundamentalanalyse: Example Corp." in result.stdout
        assert "## Quellen" in result.stdout

    def test_report_can_be_written_to_a_file(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "report.md"
        result = runner.invoke(cli.app, ["analyze", "EXMP", "--output", str(target)])
        assert result.exit_code == 0
        assert target.read_text(encoding="utf-8").startswith("# Fundamentalanalyse")

    def test_assumptions_reach_the_report(self) -> None:
        result = runner.invoke(
            cli.app, ["analyze", "EXMP", "--wacc", "0.11", "--terminal-growth", "0.015"]
        )
        assert result.exit_code == 0
        assert "WACC 11.0%" in result.stdout
        assert "terminal growth 1.5%" in result.stdout

    def test_market_data_can_be_skipped(self) -> None:
        result = runner.invoke(cli.app, ["analyze", "EXMP", "--skip-market-data"])
        assert result.exit_code == 0
        assert "DATA NOT AVAILABLE" in result.stdout

    def test_invalid_assumptions_fail_before_any_request(self) -> None:
        result = runner.invoke(
            cli.app, ["analyze", "EXMP", "--wacc", "0.04", "--terminal-growth", "0.05"]
        )
        assert result.exit_code == 2
        assert "Ungueltige Annahmen" in result.output

    def test_unknown_company_exits_with_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(self: Any, identifier: str) -> None:
            raise CompanyNotFoundError("stub", identifier)

        monkeypatch.setattr(CompleteFakeFundamentals, "resolve_company", _raise)
        result = runner.invoke(cli.app, ["analyze", "NOSUCH"])
        assert result.exit_code == 1
        assert "Datenabruf fehlgeschlagen" in result.output

    def test_help_lists_the_analyze_command(self) -> None:
        result = runner.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        assert "analyze" in result.stdout
