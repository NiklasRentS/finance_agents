"""Valuation: discounted cash flow and trading multiples.

All mathematics happens here in plain Python. No language model ever produces a
number. A DCF result is an ``ASSUMPTION`` fact, not a measurement: it states what
follows from the stated inputs, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain.facts import (
    MODEL_ASSUMPTION_SOURCE,
    Confidence,
    Fact,
    FactKind,
    Period,
    SourceRef,
)
from app.domain.financials import FinancialSnapshot, Metric, NumericFact
from app.services.metrics import RATIO, combined_confidence, derive, market_capitalisation

MAX_PROJECTION_YEARS = 15
TERMINAL_DOMINANCE_THRESHOLD = 0.75
"""Above this share of value coming from the terminal value the result is fragile."""

DEFAULT_WACC_RANGE = (0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12)
DEFAULT_TERMINAL_GROWTH_RANGE = (0.01, 0.02, 0.03, 0.04)

_CONFIDENCE_ORDER = (Confidence.UNKNOWN, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH)


@dataclass(frozen=True)
class DcfAssumptions:
    """Inputs a reader must accept before the result means anything."""

    wacc: float
    terminal_growth: float
    projection_years: int = 5
    initial_growth: float = 0.0
    fade: bool = True
    """Fade the growth rate linearly from ``initial_growth`` to ``terminal_growth``."""

    rationale: str = ""

    def __post_init__(self) -> None:
        if not 0.0 < self.wacc < 1.0:
            raise ValueError(f"wacc must be between 0 and 1, got {self.wacc}")
        if self.terminal_growth >= self.wacc:
            raise ValueError(
                f"terminal growth {self.terminal_growth} must stay below the discount rate "
                f"{self.wacc}; otherwise the perpetuity is infinite"
            )
        if not 1 <= self.projection_years <= MAX_PROJECTION_YEARS:
            raise ValueError(
                f"projection_years must be between 1 and {MAX_PROJECTION_YEARS}, "
                f"got {self.projection_years}"
            )

    def growth_path(self) -> tuple[float, ...]:
        if not self.fade or self.projection_years == 1:
            return (self.initial_growth,) * self.projection_years
        step = (self.terminal_growth - self.initial_growth) / (self.projection_years - 1)
        return tuple(self.initial_growth + step * year for year in range(self.projection_years))

    def describe(self) -> str:
        faded = " faded" if self.fade and self.projection_years > 1 else ""
        text = (
            f"WACC {self.wacc:.1%}, terminal growth {self.terminal_growth:.1%}, "
            f"{self.projection_years} projection years, initial growth "
            f"{self.initial_growth:.1%}{faded}"
        )
        return f"{text}. {self.rationale}".strip()


@dataclass(frozen=True)
class DcfYear:
    year: int
    growth: float
    free_cash_flow: float
    discount_factor: float
    present_value: float


@dataclass(frozen=True)
class DcfResult:
    assumptions: DcfAssumptions
    years: tuple[DcfYear, ...]
    enterprise_value: NumericFact
    equity_value: NumericFact
    value_per_share: NumericFact
    terminal_value_share: float | None
    """Fraction of enterprise value contributed by the terminal value."""

    @property
    def is_available(self) -> bool:
        return self.enterprise_value.is_available


def run_dcf(
    base_free_cash_flow: NumericFact,
    assumptions: DcfAssumptions,
    *,
    net_debt: NumericFact | None = None,
    shares_outstanding: NumericFact | None = None,
) -> DcfResult:
    """Value a company from its free cash flow under explicit assumptions."""
    unit = base_free_cash_flow.unit
    period = base_free_cash_flow.period
    base = base_free_cash_flow.value

    if base is None:
        return _unavailable(assumptions, unit, "free cash flow not available")
    if base <= 0:
        return _unavailable(
            assumptions,
            unit,
            "base free cash flow is not positive; a growth perpetuity is not meaningful",
        )

    years = _project(base, assumptions)
    pv_explicit = sum(year.present_value for year in years)
    final = years[-1]
    terminal_value = (
        final.free_cash_flow
        * (1.0 + assumptions.terminal_growth)
        / (assumptions.wacc - assumptions.terminal_growth)
    )
    pv_terminal = terminal_value * final.discount_factor
    enterprise = pv_explicit + pv_terminal
    terminal_share = pv_terminal / enterprise if enterprise else None

    inputs = [base_free_cash_flow]
    confidence = _confidence(inputs, terminal_share)
    note = f"Auf Basis der verwendeten Annahmen: {assumptions.describe()}"

    enterprise_fact = _assumption_fact(enterprise, unit, period, inputs, confidence, note)
    equity_fact = _equity_value(enterprise_fact, net_debt, unit, period, confidence, note)
    per_share = _per_share(equity_fact, shares_outstanding, unit, period, confidence, note)

    return DcfResult(
        assumptions=assumptions,
        years=years,
        enterprise_value=enterprise_fact,
        equity_value=equity_fact,
        value_per_share=per_share,
        terminal_value_share=terminal_share,
    )


def _project(base: float, assumptions: DcfAssumptions) -> tuple[DcfYear, ...]:
    years: list[DcfYear] = []
    cash_flow = base
    for index, growth in enumerate(assumptions.growth_path(), start=1):
        cash_flow *= 1.0 + growth
        discount_factor = 1.0 / (1.0 + assumptions.wacc) ** index
        years.append(
            DcfYear(
                year=index,
                growth=growth,
                free_cash_flow=cash_flow,
                discount_factor=discount_factor,
                present_value=cash_flow * discount_factor,
            )
        )
    return tuple(years)


def _confidence(inputs: list[NumericFact], terminal_share: float | None) -> Confidence:
    """A projection is never more certain than its inputs, and never better than medium."""
    capped = min(
        combined_confidence(inputs),
        Confidence.MEDIUM,
        key=_CONFIDENCE_ORDER.index,
    )
    if terminal_share is not None and terminal_share > TERMINAL_DOMINANCE_THRESHOLD:
        return Confidence.LOW
    return capped


def _assumption_fact(
    value: float | None,
    unit: str | None,
    period: Period | None,
    inputs: list[NumericFact],
    confidence: Confidence,
    note: str,
) -> NumericFact:
    if value is None:
        return Fact.not_available(unit=unit, note=note)
    sources: list[SourceRef] = [MODEL_ASSUMPTION_SOURCE]
    for fact in inputs:
        sources.extend(fact.sources)
    return Fact[float](
        value=value,
        unit=unit,
        period=period,
        kind=FactKind.ASSUMPTION,
        confidence=confidence,
        sources=sources,
        note=note,
    )


def _equity_value(
    enterprise: NumericFact,
    net_debt: NumericFact | None,
    unit: str | None,
    period: Period | None,
    confidence: Confidence,
    note: str,
) -> NumericFact:
    if net_debt is None or not net_debt.is_available:
        return Fact.not_available(unit=unit, note=f"{note} (net debt not available)")
    inputs = [enterprise, net_debt]
    value = enterprise.value
    if value is None:
        return Fact.not_available(unit=unit, note=note)
    return _assumption_fact(value - (net_debt.value or 0.0), unit, period, inputs, confidence, note)


def _per_share(
    equity: NumericFact,
    shares: NumericFact | None,
    unit: str | None,
    period: Period | None,
    confidence: Confidence,
    note: str,
) -> NumericFact:
    if shares is None or not shares.is_available or not shares.value:
        return Fact.not_available(unit=unit, note=f"{note} (share count not available)")
    if equity.value is None:
        return Fact.not_available(unit=unit, note=note)
    return _assumption_fact(
        equity.value / shares.value, unit, period, [equity, shares], confidence, note
    )


def _unavailable(assumptions: DcfAssumptions, unit: str | None, reason: str) -> DcfResult:
    blank: NumericFact = Fact.not_available(unit=unit, note=reason)
    return DcfResult(
        assumptions=assumptions,
        years=(),
        enterprise_value=blank,
        equity_value=blank,
        value_per_share=blank,
        terminal_value_share=None,
    )


@dataclass(frozen=True)
class SensitivityGrid:
    """Value per share across discount rate and terminal growth combinations."""

    waccs: tuple[float, ...]
    terminal_growths: tuple[float, ...]
    values: tuple[tuple[float | None, ...], ...]
    """Row per WACC, column per terminal growth. ``None`` where the model is undefined."""

    def value_at(self, wacc: float, terminal_growth: float) -> float | None:
        return self.values[self.waccs.index(wacc)][self.terminal_growths.index(terminal_growth)]

    def spread(self) -> tuple[float, float] | None:
        defined = [value for row in self.values for value in row if value is not None]
        return (min(defined), max(defined)) if defined else None


def sensitivity_grid(
    base_free_cash_flow: NumericFact,
    assumptions: DcfAssumptions,
    *,
    net_debt: NumericFact | None = None,
    shares_outstanding: NumericFact | None = None,
    waccs: tuple[float, ...] = DEFAULT_WACC_RANGE,
    terminal_growths: tuple[float, ...] = DEFAULT_TERMINAL_GROWTH_RANGE,
) -> SensitivityGrid:
    """Show how sensitive the result is to the two assumptions that drive it most."""
    rows: list[tuple[float | None, ...]] = []
    for wacc in waccs:
        row: list[float | None] = []
        for growth in terminal_growths:
            try:
                candidate = replace(assumptions, wacc=wacc, terminal_growth=growth)
            except ValueError:
                row.append(None)  # terminal growth at or above the discount rate
                continue
            result = run_dcf(
                base_free_cash_flow,
                candidate,
                net_debt=net_debt,
                shares_outstanding=shares_outstanding,
            )
            row.append(result.value_per_share.value)
        rows.append(tuple(row))
    return SensitivityGrid(
        waccs=tuple(waccs), terminal_growths=tuple(terminal_growths), values=tuple(rows)
    )


@dataclass(frozen=True)
class Multiples:
    market_cap: NumericFact
    enterprise_value: NumericFact
    price_earnings: NumericFact
    price_free_cash_flow: NumericFact
    price_book: NumericFact
    ev_ebitda: NumericFact
    ev_sales: NumericFact


def compute_multiples(
    price: NumericFact,
    snapshot: FinancialSnapshot,
    *,
    share_metric: Metric = Metric.SHARES_OUTSTANDING,
) -> Multiples:
    """Current price against the latest reported fundamentals.

    Price and fundamentals are from different dates by construction; the note on
    every fact records which reporting period the denominator belongs to.
    """
    period = snapshot.period
    note = f"Current price against {period.label} fundamentals"
    shares = snapshot.get(share_metric)
    market_cap = market_capitalisation(price, shares)
    enterprise_value = derive(
        [market_cap, snapshot.get(Metric.NET_DEBT)],
        lambda values: values[0] + values[1],
        unit=price.unit,
        period=period,
        note="Enterprise value = market capitalisation + net debt",
    )

    def ratio(numerator: NumericFact, denominator: NumericFact, label: str) -> NumericFact:
        return derive(
            [numerator, denominator],
            lambda values: values[0] / values[1] if values[1] > 0 else None,
            unit=RATIO,
            period=period,
            note=f"{label}. {note}",
        )

    return Multiples(
        market_cap=market_cap,
        enterprise_value=enterprise_value,
        price_earnings=ratio(price, snapshot.get(Metric.EPS_DILUTED), "P/E on diluted EPS"),
        price_free_cash_flow=ratio(
            market_cap, snapshot.get(Metric.FREE_CASH_FLOW), "Price / free cash flow"
        ),
        price_book=ratio(market_cap, snapshot.get(Metric.TOTAL_EQUITY), "Price / book value"),
        ev_ebitda=ratio(enterprise_value, snapshot.get(Metric.EBITDA), "EV / EBITDA"),
        ev_sales=ratio(enterprise_value, snapshot.get(Metric.REVENUE), "EV / revenue"),
    )
