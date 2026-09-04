"""Command line interface."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.exc import SQLAlchemyError

from app.agents.research import ResearchNotes, run_research
from app.config.settings import get_settings
from app.infra.logging import configure_logging
from app.ports.exceptions import ProviderError
from app.providers.ollama import OllamaClient
from app.providers.sec_edgar import SecEdgarFundamentalsProvider
from app.providers.yahoo import YahooFinanceMarketDataProvider
from app.reporting.markdown import render_markdown
from app.repositories.analysis_store import SqlAnalysisStore
from app.services.analysis import analyse_company
from app.services.valuation import DcfAssumptions

app = typer.Typer(
    help="Fundamentale Aktienrecherche aus oeffentlichen Quellen. Keine Anlageberatung.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Fundamentale Aktienrecherche aus oeffentlichen Quellen. Keine Anlageberatung."""


@app.command()
def analyze(
    ticker: Annotated[str, typer.Argument(help="Ticker oder CIK, z. B. AAPL")],
    years: Annotated[int, typer.Option(help="Anzahl der Geschaeftsjahre")] = 10,
    wacc: Annotated[float, typer.Option(help="Kapitalkosten als Dezimalzahl")] = 0.09,
    terminal_growth: Annotated[float, typer.Option(help="Ewiges Wachstum")] = 0.02,
    initial_growth: Annotated[float, typer.Option(help="Startwachstum des FCF")] = 0.04,
    projection_years: Annotated[int, typer.Option(help="Prognosejahre im DCF")] = 5,
    output: Annotated[Path | None, typer.Option(help="Zieldatei fuer den Report")] = None,
    save: Annotated[bool, typer.Option(help="Lauf in der Datenbank speichern")] = False,
    research: Annotated[
        bool, typer.Option(help="Qualitative Einordnung durch das lokale Sprachmodell")
    ] = False,
    skip_market_data: Annotated[bool, typer.Option(help="Nur Fundamentaldaten")] = False,
    verbose: Annotated[bool, typer.Option(help="Debug-Logging")] = False,
) -> None:
    """Erzeugt einen Fundamentalreport zu einem Unternehmen."""
    configure_logging(level="DEBUG" if verbose else "WARNING")
    settings = get_settings()

    try:
        assumptions = DcfAssumptions(
            wacc=wacc,
            terminal_growth=terminal_growth,
            initial_growth=initial_growth,
            projection_years=projection_years,
            rationale="Ueber die Kommandozeile gesetzt.",
        )
    except ValueError as exc:
        typer.secho(f"Ungueltige Annahmen: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    fundamentals = SecEdgarFundamentalsProvider.build(settings)
    market_data = None if skip_market_data else YahooFinanceMarketDataProvider.build(settings)
    try:
        analysis = analyse_company(
            ticker,
            fundamentals=fundamentals,
            market_data=market_data,
            assumptions=assumptions,
            max_periods=years,
        )
    except ProviderError as exc:
        typer.secho(f"Datenabruf fehlgeschlagen: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    finally:
        fundamentals.close()
        if market_data is not None:
            market_data.close()

    notes: ResearchNotes | None = None
    if research:
        llm = OllamaClient.build(settings)
        try:
            notes = run_research(analysis, llm)
        finally:
            llm.close()
        for warning in notes.warnings:
            typer.secho(warning, fg=typer.colors.YELLOW, err=True)

    report = render_markdown(analysis, notes)
    if output is None:
        typer.echo(report)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        typer.secho(f"Report geschrieben: {output}", fg=typer.colors.GREEN, err=True)

    if save:
        # Deliberately after the report exists: a database outage must not lose it.
        store = SqlAnalysisStore.from_settings(settings)
        try:
            run_id = store.save_run(analysis, report_markdown=report)
        except SQLAlchemyError as exc:
            typer.secho(f"Speichern fehlgeschlagen: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=3) from exc
        finally:
            store.close()
        typer.secho(f"Lauf gespeichert: {run_id}", fg=typer.colors.GREEN, err=True)


@app.command()
def runs(
    ticker: Annotated[str | None, typer.Option(help="Nur Laeufe zu diesem Ticker")] = None,
    limit: Annotated[int, typer.Option(help="Maximale Anzahl")] = 20,
) -> None:
    """Listet gespeicherte Laeufe, neueste zuerst."""
    store = SqlAnalysisStore.from_settings(get_settings())
    try:
        summaries = store.list_runs(ticker=ticker, limit=limit)
    except SQLAlchemyError as exc:
        typer.secho(f"Datenbankzugriff fehlgeschlagen: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc
    finally:
        store.close()

    if not summaries:
        typer.secho("Keine gespeicherten Laeufe.", err=True)
        return
    for summary in summaries:
        value = (
            "DATA NOT AVAILABLE"
            if summary.value_per_share is None
            else f"{summary.value_per_share:,.2f} {summary.currency or ''}".strip()
        )
        typer.echo(
            f"{summary.id}  {summary.generated_at:%Y-%m-%d %H:%M}  "
            f"{summary.ticker:<6} {summary.company_name:<30.30} "
            f"{summary.period_label or '-':<8} DCF {value}"
        )


@app.command()
def report(
    run_id: Annotated[str, typer.Argument(help="Kennung eines gespeicherten Laufs")],
    output: Annotated[Path | None, typer.Option(help="Zieldatei fuer den Report")] = None,
) -> None:
    """Gibt den gespeicherten Report eines Laufs aus."""
    try:
        identifier = uuid.UUID(run_id)
    except ValueError as exc:
        typer.secho(f"Keine gueltige Lauf-Kennung: {run_id}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    store = SqlAnalysisStore.from_settings(get_settings())
    try:
        markdown = store.load_report(identifier)
    except SQLAlchemyError as exc:
        typer.secho(f"Datenbankzugriff fehlgeschlagen: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc
    finally:
        store.close()

    if markdown is None:
        typer.secho(f"Kein Report zu Lauf {run_id} gespeichert.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if output is None:
        typer.echo(markdown)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    typer.secho(f"Report geschrieben: {output}", fg=typer.colors.GREEN, err=True)


if __name__ == "__main__":
    app()
