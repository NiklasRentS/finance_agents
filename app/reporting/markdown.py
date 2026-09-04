"""Markdown rendering of a research report.

Two rules govern this module: nothing is printed that is not backed by a fact,
and everything that is missing is named explicitly instead of being omitted.
"""

from __future__ import annotations

from app.domain.facts import Confidence, Fact, FactKind, SourceRef
from app.domain.financials import Metric, NumericFact
from app.services.analysis import HEADLINE_METRICS, RATIO_METRICS, CompanyAnalysis
from app.services.valuation import Multiples, SensitivityGrid

DISCLAIMER = (
    "Dieser Bericht ist eine strukturierte Aufbereitung oeffentlich verfuegbarer Daten "
    "und ausdruecklich **keine Anlageberatung und keine Kauf- oder Verkaufsempfehlung**. "
    "Alle Bewertungsergebnisse gelten nur unter den angegebenen Annahmen."
)

METRIC_LABELS: dict[Metric, str] = {
    Metric.REVENUE: "Umsatz",
    Metric.GROSS_PROFIT: "Bruttoergebnis",
    Metric.OPERATING_INCOME: "Operatives Ergebnis",
    Metric.EBITDA: "EBITDA",
    Metric.NET_INCOME: "Jahresueberschuss",
    Metric.EPS_DILUTED: "Ergebnis je Aktie (verwaessert)",
    Metric.OPERATING_CASH_FLOW: "Operativer Cashflow",
    Metric.CAPITAL_EXPENDITURE: "Investitionen",
    Metric.FREE_CASH_FLOW: "Free Cash Flow",
    Metric.TOTAL_ASSETS: "Bilanzsumme",
    Metric.TOTAL_EQUITY: "Eigenkapital",
    Metric.TOTAL_DEBT: "Finanzverbindlichkeiten",
    Metric.NET_DEBT: "Nettoverschuldung",
    Metric.SHARES_OUTSTANDING: "Ausstehende Aktien",
    Metric.SHARES_DILUTED: "Aktien (verwaessert)",
    Metric.REVENUE_GROWTH: "Umsatzwachstum",
    Metric.GROSS_MARGIN: "Bruttomarge",
    Metric.OPERATING_MARGIN: "Operative Marge",
    Metric.EBITDA_MARGIN: "EBITDA-Marge",
    Metric.NET_MARGIN: "Nettomarge",
    Metric.FCF_MARGIN: "FCF-Marge",
    Metric.ROE: "Eigenkapitalrendite",
    Metric.ROIC: "Kapitalrendite (ROIC)",
}

TREND_LABELS = {
    "RISING": "steigend",
    "FALLING": "fallend",
    "STABLE": "stabil",
    "UNKNOWN": "nicht bestimmbar",
}

MILLION = 1e6
NOT_AVAILABLE = "DATA NOT AVAILABLE"

PER_SHARE_METRICS = frozenset({Metric.EPS_BASIC, Metric.EPS_DILUTED})
SHARE_COUNT_METRICS = frozenset({Metric.SHARES_OUTSTANDING, Metric.SHARES_DILUTED})


class SourceIndex:
    """Numbered bibliography built from the facts that were actually used."""

    def __init__(self) -> None:
        self._order: list[SourceRef] = []
        self._keys: dict[tuple[str, str | None, str | None], int] = {}

    def add(self, source: SourceRef) -> int:
        key = (source.provider, source.document_id, source.url)
        if key not in self._keys:
            self._order.append(source)
            self._keys[key] = len(self._order)
        return self._keys[key]

    def mark(self, fact: Fact[float] | Fact[str]) -> str:
        """Return footnote markers such as ``[1][2]`` for a fact's sources."""
        numbers = sorted({self.add(source) for source in fact.sources})
        return "".join(f"[{number}]" for number in numbers)

    def entries(self) -> list[tuple[int, SourceRef]]:
        return list(enumerate(self._order, start=1))


def render_markdown(analysis: CompanyAnalysis) -> str:
    """Render a complete report. Never raises on missing data."""
    sources = SourceIndex()
    body = "\n".join(
        [
            *_header(analysis),
            *_warnings(analysis),
            *_headline_figures(analysis, sources),
            *_ratios(analysis, sources),
            *_history_table(analysis),
            *_trends(analysis),
            *_market(analysis, sources),
            *_valuation(analysis, sources),
            *_sensitivity(analysis.sensitivity, analysis.history.currency),
            *_data_gaps(analysis),
            *_bibliography(sources),
        ]
    )
    return body.rstrip() + "\n"


def _header(analysis: CompanyAnalysis) -> list[str]:
    company = analysis.company
    identifiers = [f"Ticker: {analysis.ticker}"]
    if company.cik:
        identifiers.append(f"CIK: {company.cik}")
    if company.reporting_currency:
        identifiers.append(f"Berichtswaehrung: {company.reporting_currency}")
    return [
        f"# Fundamentalanalyse: {company.name}",
        "",
        " | ".join(identifiers),
        "",
        f"Erstellt am {analysis.generated_at:%Y-%m-%d %H:%M} UTC",
        "",
        f"> {DISCLAIMER}",
        "",
    ]


def _warnings(analysis: CompanyAnalysis) -> list[str]:
    if not analysis.warnings:
        return []
    return ["## Einschraenkungen dieses Laufs", "", *[f"- {w}" for w in analysis.warnings], ""]


def _headline_figures(analysis: CompanyAnalysis, sources: SourceIndex) -> list[str]:
    snapshot = analysis.latest
    if snapshot is None:
        return ["## Kennzahlen", "", NOT_AVAILABLE, ""]
    lines = [
        f"## Kennzahlen {snapshot.period.label}",
        "",
        "| Kennzahl | Wert | Quelle |",
        "| --- | ---: | --- |",
    ]
    for metric in HEADLINE_METRICS:
        fact = snapshot.get(metric)
        lines.append(
            f"| {METRIC_LABELS.get(metric, metric.value)} | "
            f"{format_metric(metric, fact, analysis.history.currency)} | {sources.mark(fact)} |"
        )
    lines.append("")
    return lines


def _ratios(analysis: CompanyAnalysis, sources: SourceIndex) -> list[str]:
    snapshot = analysis.latest
    if snapshot is None:
        return []
    lines = ["## Margen und Renditen", "", "| Kennzahl | Wert | Quelle |", "| --- | ---: | --- |"]
    for metric in RATIO_METRICS:
        fact = snapshot.get(metric)
        lines.append(
            f"| {METRIC_LABELS.get(metric, metric.value)} | "
            f"{_format_percent(fact)} | {sources.mark(fact)} |"
        )
    lines.append("")
    return lines


def _history_table(analysis: CompanyAnalysis) -> list[str]:
    snapshots = analysis.history.sorted_snapshots()
    if not snapshots:
        return []
    currency = analysis.history.currency
    metrics = (
        Metric.REVENUE,
        Metric.OPERATING_INCOME,
        Metric.NET_INCOME,
        Metric.FREE_CASH_FLOW,
        Metric.GROSS_MARGIN,
        Metric.OPERATING_MARGIN,
        Metric.ROIC,
    )
    header = "| Kennzahl | " + " | ".join(s.period.label for s in snapshots) + " |"
    divider = "| --- | " + " | ".join("---:" for _ in snapshots) + " |"
    lines = [f"## Historie (Betraege in Mio. {currency or ''})".rstrip(), "", header, divider]
    for metric in metrics:
        cells = []
        for snapshot in snapshots:
            cells.append(format_metric(metric, snapshot.get(metric), None))
        lines.append(f"| {METRIC_LABELS.get(metric, metric.value)} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _trends(analysis: CompanyAnalysis) -> list[str]:
    if not analysis.trends:
        return []
    lines = [
        "## Entwicklung",
        "",
        "Richtungsangaben sind rein rechnerisch und enthalten keine Bewertung.",
        "",
        "| Kennzahl | Richtung | CAGR | Perioden |",
        "| --- | --- | ---: | ---: |",
    ]
    for metric, trend in analysis.trends.items():
        lines.append(
            f"| {METRIC_LABELS.get(metric, metric.value)} "
            f"| {TREND_LABELS.get(trend.direction.value, trend.direction.value)} "
            f"| {_format_percent(trend.cagr)} | {trend.periods} |"
        )
    lines.append("")
    return lines


def _market(analysis: CompanyAnalysis, sources: SourceIndex) -> list[str]:
    quote = analysis.quote
    if quote is None:
        return ["## Marktdaten", "", NOT_AVAILABLE, ""]
    lines = [
        "## Marktdaten",
        "",
        f"Kurs: {quote.price.display()} {sources.mark(quote.price)}"
        + (f" (Stand {quote.as_of})" if quote.as_of else ""),
        "",
    ]
    if analysis.multiples is not None:
        lines.extend(_multiples_table(analysis.multiples, sources, analysis.history.currency))
    return lines


def _multiples_table(multiples: Multiples, sources: SourceIndex, currency: str | None) -> list[str]:
    rows: list[tuple[str, NumericFact, bool]] = [
        ("Marktkapitalisierung", multiples.market_cap, True),
        ("Unternehmenswert (EV)", multiples.enterprise_value, True),
        ("KGV (verwaessert)", multiples.price_earnings, False),
        ("Kurs / Free Cash Flow", multiples.price_free_cash_flow, False),
        ("Kurs / Buchwert", multiples.price_book, False),
        ("EV / EBITDA", multiples.ev_ebitda, False),
        ("EV / Umsatz", multiples.ev_sales, False),
    ]
    lines = ["| Kennzahl | Wert | Quelle |", "| --- | ---: | --- |"]
    for label, fact, is_money in rows:
        value = _format_money(fact, currency) if is_money else _format_ratio(fact)
        lines.append(f"| {label} | {value} | {sources.mark(fact)} |")
    lines.append("")
    return lines


def _valuation(analysis: CompanyAnalysis, sources: SourceIndex) -> list[str]:
    result = analysis.valuation
    currency = analysis.history.currency
    lines = [
        "## Bewertung (DCF)",
        "",
        f"Annahmen: {analysis.assumptions.describe()}",
        "",
    ]
    if not result.is_available:
        lines.extend([f"Ergebnis: {NOT_AVAILABLE}", "", result.enterprise_value.note or "", ""])
        return lines

    lines.extend(
        [
            "| Jahr | Wachstum | Free Cash Flow | Barwert |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for year in result.years:
        lines.append(
            f"| {year.year} | {year.growth:.2%} | "
            f"{year.free_cash_flow / MILLION:,.0f} | {year.present_value / MILLION:,.0f} |"
        )
    share = result.terminal_value_share
    terminal_line = (
        f"- Anteil des Terminal Value am Unternehmenswert: {share:.0%}"
        if share is not None
        else f"- Anteil des Terminal Value am Unternehmenswert: {NOT_AVAILABLE}"
    )
    lines.extend(
        [
            "",
            f"- Unternehmenswert: {_format_money(result.enterprise_value, currency)} "
            f"{sources.mark(result.enterprise_value)}",
            f"- Eigenkapitalwert: {_format_money(result.equity_value, currency)}",
            f"- Wert je Aktie: {result.value_per_share.display()}",
            terminal_line,
            "",
        ]
    )
    if share is not None and share > 0.75:
        lines.extend(
            [
                "> Der Terminal Value dominiert das Ergebnis. Der Wert haengt damit "
                "staerker von den Annahmen ab als von den Daten.",
                "",
            ]
        )
    return lines


def _sensitivity(grid: SensitivityGrid, currency: str | None) -> list[str]:
    if not grid.values:
        return []
    header = "| WACC \\ ewiges Wachstum | " + " | ".join(f"{g:.1%}" for g in grid.terminal_growths)
    lines = [
        f"## Sensitivitaet: Wert je Aktie in {currency or 'Waehrung der Berichte'}",
        "",
        header + " |",
        "| --- | " + " | ".join("---:" for _ in grid.terminal_growths) + " |",
    ]
    for wacc, row in zip(grid.waccs, grid.values, strict=True):
        cells = " | ".join("n/a" if value is None else f"{value:,.2f}" for value in row)
        lines.append(f"| {wacc:.1%} | {cells} |")
    spread = grid.spread()
    lines.append("")
    if spread is not None:
        lines.extend(
            [f"Spannweite ueber alle Kombinationen: {spread[0]:,.2f} bis {spread[1]:,.2f}.", ""]
        )
    return lines


def _data_gaps(analysis: CompanyAnalysis) -> list[str]:
    missing = analysis.missing_metrics()
    if not missing:
        return ["## Datenluecken", "", "Alle angeforderten Kennzahlen waren verfuegbar.", ""]
    return [
        "## Datenluecken",
        "",
        "Die folgenden Kennzahlen konnten aus den genutzten Quellen nicht belegt werden "
        "und wurden nicht geschaetzt:",
        "",
        *[f"- {METRIC_LABELS.get(metric, metric.value)}: {NOT_AVAILABLE}" for metric in missing],
        "",
    ]


def _bibliography(sources: SourceIndex) -> list[str]:
    entries = sources.entries()
    if not entries:
        return []
    return [
        "## Quellen",
        "",
        *[f"{number}. {source.citation()}" for number, source in entries],
        "",
    ]


def format_metric(metric: Metric, fact: NumericFact, currency: str | None) -> str:
    """Render a value in the unit the metric is actually measured in."""
    if fact.value is None:
        return NOT_AVAILABLE
    if fact.unit == "ratio":
        return _format_percent(fact)
    if metric in PER_SHARE_METRICS:
        return _annotate(f"{fact.value:,.2f}{f' {currency}' if currency else ''}", fact)
    if metric in SHARE_COUNT_METRICS:
        return _annotate(f"{fact.value / MILLION:,.0f} Mio. Stueck", fact)
    return _format_money(fact, currency)


def _format_money(fact: NumericFact, currency: str | None) -> str:
    if fact.value is None:
        return NOT_AVAILABLE
    text = f"{fact.value / MILLION:,.0f}"
    if currency:
        text = f"{text} Mio. {currency}"
    return _annotate(text, fact)


def _format_percent(fact: NumericFact) -> str:
    if fact.value is None:
        return NOT_AVAILABLE
    return _annotate(f"{fact.value:.1%}", fact)


def _format_ratio(fact: NumericFact) -> str:
    if fact.value is None:
        return NOT_AVAILABLE
    return _annotate(f"{fact.value:,.1f}x", fact)


def _annotate(text: str, fact: NumericFact) -> str:
    if fact.kind is FactKind.ASSUMPTION:
        text = f"{text} [ASSUMPTION]"
    if fact.confidence is Confidence.LOW:
        text = f"{text} [LOW CONFIDENCE]"
    return text
