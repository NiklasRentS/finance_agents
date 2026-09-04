"""Command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from app.config.settings import get_settings
from app.infra.logging import configure_logging
from app.ports.exceptions import ProviderError
from app.providers.sec_edgar import SecEdgarFundamentalsProvider
from app.providers.yahoo import YahooFinanceMarketDataProvider
from app.reporting.markdown import render_markdown
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

    report = render_markdown(analysis)
    if output is None:
        typer.echo(report)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    typer.secho(f"Report geschrieben: {output}", fg=typer.colors.GREEN, err=True)


if __name__ == "__main__":
    app()
