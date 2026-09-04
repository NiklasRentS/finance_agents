"""Derived financial metrics.

Every value produced here is a ``DERIVED`` fact that inherits the sources of its
inputs. If any input is missing the result is N/A: no interpolation, no
substitution, no silent zeros.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

import numpy as np

from app.domain.facts import Confidence, Fact, Period, SourceRef
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric, NumericFact

DAYS_PER_YEAR = 365.25
STABLE_SLOPE_THRESHOLD = 0.02
RATIO = "ratio"

SPLIT_JUMP_THRESHOLD = 0.4
SHARE_COUNT_METRICS = (Metric.SHARES_DILUTED, Metric.SHARES_OUTSTANDING)
SPLIT_NOTE = (
    "As-filed share count from before an apparent stock split: not split-adjusted "
    "and therefore not comparable with later periods"
)

_CONFIDENCE_RANK = {
    Confidence.UNKNOWN: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}
_RANK_TO_CONFIDENCE = {rank: conf for conf, rank in _CONFIDENCE_RANK.items()}


def merge_sources(facts: Iterable[NumericFact]) -> list[SourceRef]:
    """Union of the input sources, de-duplicated and order preserving."""
    merged: dict[tuple[str, str | None, str | None], SourceRef] = {}
    for fact in facts:
        for source in fact.sources:
            merged.setdefault((source.provider, source.document_id, source.locator), source)
    return list(merged.values())


def combined_confidence(facts: Sequence[NumericFact]) -> Confidence:
    """A derived value is never more trustworthy than its weakest input."""
    if not facts:
        return Confidence.UNKNOWN
    return _RANK_TO_CONFIDENCE[min(_CONFIDENCE_RANK[f.confidence] for f in facts)]


def derive(
    inputs: Sequence[NumericFact],
    compute: Callable[[list[float]], float | None],
    *,
    unit: str | None,
    period: Period | None,
    note: str,
) -> NumericFact:
    """Compute a value from other facts, propagating provenance and N/A."""
    values = [fact.value for fact in inputs]
    if any(value is None for value in values):
        return Fact.not_available(unit=unit, period=period, note=f"{note} (input missing)")
    result = compute([float(value) for value in values if value is not None])
    if result is None:
        return Fact.not_available(unit=unit, period=period, note=f"{note} (undefined)")
    return Fact.derived(
        result,
        unit=unit,
        period=period,
        sources=merge_sources(inputs),
        confidence=combined_confidence(inputs),
        note=note,
    )


def _subtract(values: list[float]) -> float:
    return values[0] - values[1]


def _add(values: list[float]) -> float:
    return values[0] + values[1]


def _ratio(values: list[float]) -> float | None:
    return values[0] / values[1] if values[1] != 0 else None


def _net_debt(values: list[float]) -> float:
    return values[0] - values[1] - values[2]


def _invested_capital(values: list[float]) -> float:
    return values[0] + values[1] - values[2]


def _roic(values: list[float]) -> float | None:
    ebit, tax_expense, pretax_income, invested_capital = values
    if pretax_income <= 0 or invested_capital == 0:
        return None
    effective_tax_rate = tax_expense / pretax_income
    return ebit * (1.0 - effective_tax_rate) / invested_capital


@dataclass(frozen=True)
class Derivation:
    metric: Metric
    inputs: tuple[Metric, ...]
    compute: Callable[[list[float]], float | None]
    note: str
    unit: str | None = None
    """None inherits the unit of the first input."""


DERIVATIONS: tuple[Derivation, ...] = (
    Derivation(
        Metric.GROSS_PROFIT,
        (Metric.REVENUE, Metric.COST_OF_REVENUE),
        _subtract,
        "Gross profit = revenue - cost of revenue",
    ),
    Derivation(
        Metric.EBIT,
        (Metric.OPERATING_INCOME,),
        lambda v: v[0],
        "EBIT taken from reported operating income",
    ),
    Derivation(
        Metric.EBITDA,
        (Metric.EBIT, Metric.DEPRECIATION_AMORTIZATION),
        _add,
        "EBITDA = EBIT + depreciation & amortisation",
    ),
    Derivation(
        Metric.FREE_CASH_FLOW,
        (Metric.OPERATING_CASH_FLOW, Metric.CAPITAL_EXPENDITURE),
        _subtract,
        "Free cash flow = operating cash flow - capital expenditure",
    ),
    Derivation(
        Metric.TOTAL_DEBT,
        (Metric.SHORT_TERM_DEBT, Metric.LONG_TERM_DEBT),
        _add,
        "Total debt = short-term debt + long-term debt",
    ),
    Derivation(
        Metric.NET_DEBT,
        (Metric.TOTAL_DEBT, Metric.CASH_AND_EQUIVALENTS, Metric.SHORT_TERM_INVESTMENTS),
        _net_debt,
        "Net debt = total debt - cash - short-term investments",
    ),
    Derivation(
        Metric.WORKING_CAPITAL,
        (Metric.TOTAL_CURRENT_ASSETS, Metric.TOTAL_CURRENT_LIABILITIES),
        _subtract,
        "Working capital = current assets - current liabilities",
    ),
    Derivation(
        Metric.INVESTED_CAPITAL,
        (Metric.TOTAL_EQUITY, Metric.TOTAL_DEBT, Metric.CASH_AND_EQUIVALENTS),
        _invested_capital,
        "Invested capital = equity + total debt - cash",
    ),
    Derivation(
        Metric.GROSS_MARGIN,
        (Metric.GROSS_PROFIT, Metric.REVENUE),
        _ratio,
        "Gross margin = gross profit / revenue",
        unit=RATIO,
    ),
    Derivation(
        Metric.OPERATING_MARGIN,
        (Metric.OPERATING_INCOME, Metric.REVENUE),
        _ratio,
        "Operating margin = operating income / revenue",
        unit=RATIO,
    ),
    Derivation(
        Metric.EBITDA_MARGIN,
        (Metric.EBITDA, Metric.REVENUE),
        _ratio,
        "EBITDA margin = EBITDA / revenue",
        unit=RATIO,
    ),
    Derivation(
        Metric.NET_MARGIN,
        (Metric.NET_INCOME, Metric.REVENUE),
        _ratio,
        "Net margin = net income / revenue",
        unit=RATIO,
    ),
    Derivation(
        Metric.FCF_MARGIN,
        (Metric.FREE_CASH_FLOW, Metric.REVENUE),
        _ratio,
        "FCF margin = free cash flow / revenue",
        unit=RATIO,
    ),
    Derivation(
        Metric.ROE,
        (Metric.NET_INCOME, Metric.TOTAL_EQUITY),
        _ratio,
        "ROE = net income / total equity at period end",
        unit=RATIO,
    ),
    Derivation(
        Metric.ROIC,
        (Metric.EBIT, Metric.INCOME_TAX_EXPENSE, Metric.PRETAX_INCOME, Metric.INVESTED_CAPITAL),
        _roic,
        "ROIC = EBIT x (1 - effective tax rate) / invested capital at period end",
        unit=RATIO,
    ),
)


def enrich(history: FinancialHistory) -> FinancialHistory:
    """Return a copy of ``history`` with derived metrics added."""
    enriched: list[FinancialSnapshot] = []
    previous: FinancialSnapshot | None = None
    for snapshot in history.sorted_snapshots():
        values = dict(snapshot.values)
        for derivation in DERIVATIONS:
            existing = values.get(derivation.metric)
            if existing is not None and existing.is_available:
                continue
            inputs = [
                values.get(metric)
                or Fact.not_available(period=snapshot.period, note=f"{metric} not reported")
                for metric in derivation.inputs
            ]
            unit = derivation.unit if derivation.unit is not None else inputs[0].unit
            values[derivation.metric] = derive(
                inputs,
                derivation.compute,
                unit=unit,
                period=snapshot.period,
                note=derivation.note,
            )
        growth = _revenue_growth(previous, snapshot)
        if growth is not None:
            values[Metric.REVENUE_GROWTH] = growth
        current = FinancialSnapshot(period=snapshot.period, values=values)
        enriched.append(current)
        previous = current
    return FinancialHistory(
        currency=history.currency, snapshots=flag_split_discontinuities(enriched)
    )


def flag_split_discontinuities(
    snapshots: Sequence[FinancialSnapshot],
    *,
    threshold: float = SPLIT_JUMP_THRESHOLD,
) -> list[FinancialSnapshot]:
    """Mark share counts that predate an apparent stock split as low confidence.

    XBRL company facts are as-filed. A 10-K restates only the years it contains, so
    older periods keep their pre-split share count. Comparing them with later periods
    silently inverts buyback trends, which is why the affected values are downgraded
    instead of being adjusted with a split factor we do not have a source for.
    """
    values = [dict(snapshot.values) for snapshot in snapshots]
    for metric in SHARE_COUNT_METRICS:
        points = [
            (index, snapshot_values[metric])
            for index, snapshot_values in enumerate(values)
            if metric in snapshot_values and snapshot_values[metric].is_available
        ]
        break_index = _last_discontinuity(points, threshold)
        if break_index is None:
            continue
        for index, fact in points:
            if index < break_index:
                values[index][metric] = fact.model_copy(
                    update={"confidence": Confidence.LOW, "note": SPLIT_NOTE}
                )
    return [
        FinancialSnapshot(period=snapshot.period, values=snapshot_values)
        for snapshot, snapshot_values in zip(snapshots, values, strict=True)
    ]


def _last_discontinuity(points: Sequence[tuple[int, NumericFact]], threshold: float) -> int | None:
    break_index: int | None = None
    for (_, previous), (index, current) in pairwise(points):
        if previous.value is None or current.value is None or previous.value <= 0:
            continue
        if abs(current.value / previous.value - 1.0) > threshold:
            break_index = index
    return break_index


def _has_split_discontinuity(series: Sequence[tuple[Period, NumericFact]]) -> bool:
    points = [(index, fact) for index, (_, fact) in enumerate(series) if fact.is_available]
    return _last_discontinuity(points, SPLIT_JUMP_THRESHOLD) is not None


def _revenue_growth(
    previous: FinancialSnapshot | None, current: FinancialSnapshot
) -> NumericFact | None:
    if previous is None:
        return None
    return derive(
        [current.get(Metric.REVENUE), previous.get(Metric.REVENUE)],
        lambda v: (v[0] / v[1] - 1.0) if v[1] != 0 else None,
        unit=RATIO,
        period=current.period,
        note=f"Revenue growth vs. {previous.period.label}",
    )


class TrendDirection(StrEnum):
    """Purely mathematical direction. Whether rising is good depends on the metric."""

    RISING = "RISING"
    FALLING = "FALLING"
    STABLE = "STABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TrendSummary:
    metric: Metric
    periods: int
    first: float | None
    last: float | None
    cagr: NumericFact
    direction: TrendDirection


def cagr(first: float, last: float, years: float) -> float | None:
    """Compound annual growth rate. Undefined for non-positive endpoints."""
    if years <= 0 or first <= 0 or last <= 0:
        return None
    return float((last / first) ** (1.0 / years)) - 1.0


def analyse_trend(
    history: FinancialHistory,
    metric: Metric,
    *,
    threshold: float = STABLE_SLOPE_THRESHOLD,
) -> TrendSummary:
    """Summarise how a metric developed across the available periods."""
    available = history.available_series(metric)
    if len(available) < 2:
        return TrendSummary(
            metric=metric,
            periods=len(available),
            first=available[0][1] if available else None,
            last=available[-1][1] if available else None,
            cagr=Fact.not_available(note="fewer than two observations"),
            direction=TrendDirection.UNKNOWN,
        )

    periods = [period for period, _ in available]
    values = [value for _, value in available]
    years = (periods[-1].end - periods[0].end).days / DAYS_PER_YEAR

    series = history.series(metric)
    if metric in SHARE_COUNT_METRICS and _has_split_discontinuity(series):
        return TrendSummary(
            metric=metric,
            periods=len(available),
            first=values[0],
            last=values[-1],
            cagr=Fact.not_available(unit=RATIO, note=SPLIT_NOTE),
            direction=TrendDirection.UNKNOWN,
        )

    endpoint_facts = [fact for period, fact in series if period in (periods[0], periods[-1])]
    growth = cagr(values[0], values[-1], years)
    cagr_fact = (
        Fact.derived(
            growth,
            unit=RATIO,
            period=periods[-1],
            sources=merge_sources(endpoint_facts),
            confidence=combined_confidence(endpoint_facts),
            note=f"CAGR {periods[0].label} to {periods[-1].label}",
        )
        if growth is not None
        else Fact.not_available(
            unit=RATIO, note="CAGR undefined for non-positive or zero-length endpoints"
        )
    )

    return TrendSummary(
        metric=metric,
        periods=len(available),
        first=values[0],
        last=values[-1],
        cagr=cagr_fact,
        direction=_direction(values, threshold),
    )


def _direction(values: list[float], threshold: float) -> TrendDirection:
    scale = float(np.mean(np.abs(values)))
    if scale == 0:
        return TrendDirection.STABLE
    slope = float(np.polyfit(np.arange(len(values), dtype=float), np.array(values), 1)[0])
    normalised = slope / scale
    if normalised > threshold:
        return TrendDirection.RISING
    if normalised < -threshold:
        return TrendDirection.FALLING
    return TrendDirection.STABLE


def market_capitalisation(price: NumericFact, shares: NumericFact) -> NumericFact:
    """Market cap from a price and a share count, citing both sources."""
    return derive(
        [price, shares],
        lambda v: v[0] * v[1],
        unit=price.unit,
        period=shares.period or price.period,
        note="Market capitalisation = share price x shares outstanding",
    )
