"""Tests for the command line interface."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from typer.testing import CliRunner

from app import cli
from app.ports.exceptions import CompanyNotFoundError
from app.repositories.analysis_store import SqlAnalysisStore
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


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[SqlAnalysisStore]:
    """Point the CLI at a throwaway SQLite database instead of Postgres."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    instance = SqlAnalysisStore(engine)
    instance.create_schema()
    monkeypatch.setattr(instance, "close", lambda: None)
    monkeypatch.setattr(
        "app.cli.SqlAnalysisStore.from_settings",
        classmethod(lambda cls, settings: instance),
    )
    yield instance
    engine.dispose()


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


class TestPersistence:
    def test_a_run_can_be_saved_and_listed_again(self, store: SqlAnalysisStore) -> None:
        saved = runner.invoke(cli.app, ["analyze", "EXMP", "--save"])
        assert saved.exit_code == 0
        assert "Lauf gespeichert" in saved.output

        listed = runner.invoke(cli.app, ["runs"])
        assert listed.exit_code == 0
        assert "EXMP" in listed.stdout
        assert str(store.list_runs()[0].id) in listed.stdout

    def test_the_stored_report_can_be_printed(self, store: SqlAnalysisStore) -> None:
        runner.invoke(cli.app, ["analyze", "EXMP", "--save"])
        run_id = str(store.list_runs()[0].id)
        result = runner.invoke(cli.app, ["report", run_id])
        assert result.exit_code == 0
        assert "# Fundamentalanalyse: Example Corp." in result.stdout

    def test_an_empty_database_says_so(self, store: SqlAnalysisStore) -> None:
        result = runner.invoke(cli.app, ["runs"])
        assert result.exit_code == 0
        assert "Keine gespeicherten Laeufe" in result.output

    def test_an_unknown_run_is_reported_as_missing(self, store: SqlAnalysisStore) -> None:
        result = runner.invoke(cli.app, ["report", "3f8b9c1e-0000-4000-8000-000000000000"])
        assert result.exit_code == 1
        assert "Kein Report" in result.output

    def test_a_malformed_run_id_is_rejected(self, store: SqlAnalysisStore) -> None:
        result = runner.invoke(cli.app, ["report", "nonsense"])
        assert result.exit_code == 2
        assert "Keine gueltige Lauf-Kennung" in result.output

    def test_the_report_survives_a_database_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fail(self: Any, *args: Any, **kwargs: Any) -> None:
            raise OperationalError("INSERT", {}, Exception("database is unreachable"))

        monkeypatch.setattr(
            "app.cli.SqlAnalysisStore.from_settings",
            classmethod(lambda cls, settings: SqlAnalysisStore(create_engine("sqlite://"))),
        )
        monkeypatch.setattr(SqlAnalysisStore, "save_run", _fail)
        result = runner.invoke(cli.app, ["analyze", "EXMP", "--save"])
        assert result.exit_code == 3
        assert "# Fundamentalanalyse: Example Corp." in result.stdout
        assert "Speichern fehlgeschlagen" in result.output
