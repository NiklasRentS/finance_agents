"""Qualitative research agent.

The model receives facts that already carry sources and phrases observations
about them. Every sentence it returns is validated afterwards: a statement that
cites a fact we never supplied, or that contains a number we never supplied, is
discarded rather than repaired. Silence is preferable to an invented figure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.facts import SourceRef
from app.domain.financials import NumericFact
from app.infra.logging import get_logger
from app.ports.exceptions import ProviderError
from app.ports.llm import LlmClient, LlmMessage, Role
from app.reporting.markdown import METRIC_LABELS, TREND_LABELS, format_metric
from app.services.analysis import HEADLINE_METRICS, RATIO_METRICS, CompanyAnalysis

logger = get_logger(__name__)

PROMPTS = Path(__file__).parent / "prompts"
MAX_NOTES = 8
MAX_STATEMENT_CHARS = 400

# Thousands separators are removed, decimal separators are unified, so that
# "416,161" from a fact and "416.161" from the model compare equal.
_THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")
_NUMBER = re.compile(r"\d[\d.,]*")
# Models like to repeat the citation inline ("... (F5)"). Those digits are our
# own numbering, not a claim about the company.
_FACT_REFERENCE = re.compile(r"\bF\d+\b")


class FindingCategory(StrEnum):
    OBSERVATION = "OBSERVATION"
    TREND = "TREND"
    RISK = "RISK"
    DATA_GAP = "DATA_GAP"


class ResearchFinding(BaseModel):
    """One statement as returned by the model, before validation."""

    model_config = ConfigDict(frozen=True)

    category: FindingCategory
    statement: str
    fact_ids: list[str] = Field(default_factory=list)


class ResearchOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    findings: list[ResearchFinding] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class FactCard:
    """A fact in the form the model sees it."""

    id: str
    label: str
    value: str
    sources: tuple[SourceRef, ...]

    def render(self) -> str:
        return f"{self.id}: {self.label} = {self.value}"

    def numbers(self) -> set[str]:
        return _numbers(f"{self.label} {self.value}")


@dataclass(frozen=True)
class ResearchNote:
    """A statement that survived validation, with the sources behind it."""

    category: FindingCategory
    statement: str
    fact_ids: tuple[str, ...]
    sources: tuple[SourceRef, ...]


@dataclass(frozen=True)
class ResearchNotes:
    model: str
    notes: tuple[ResearchNote, ...] = ()
    open_questions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rejected: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.notes and not self.open_questions


def run_research(
    analysis: CompanyAnalysis, llm: LlmClient, *, max_notes: int = MAX_NOTES
) -> ResearchNotes:
    """Ask the model for observations and keep only the defensible ones."""
    cards = build_fact_cards(analysis)
    if not cards:
        return ResearchNotes(model=llm.name, warnings=("Keine Fakten fuer die Einordnung.",))
    if not llm.is_available():
        return ResearchNotes(
            model=llm.name,
            warnings=("Sprachmodell nicht erreichbar: keine qualitative Einordnung erzeugt.",),
        )

    messages = _messages(analysis, cards, max_notes=max_notes)
    try:
        response = llm.complete(messages, json_schema=ResearchOutput.model_json_schema())
    except ProviderError as exc:
        logger.warning("research.llm_failed", error=str(exc))
        return ResearchNotes(
            model=llm.name,
            warnings=(f"Sprachmodell nicht nutzbar: {exc}",),
        )

    try:
        output = ResearchOutput.model_validate_json(response.text)
    except (ValidationError, ValueError) as exc:
        logger.warning("research.invalid_output", error=str(exc))
        return ResearchNotes(
            model=response.model,
            warnings=("Antwort des Sprachmodells war nicht auswertbar und wurde verworfen.",),
        )

    return _validate(output, cards, model=response.model, max_notes=max_notes)


def build_fact_cards(analysis: CompanyAnalysis) -> list[FactCard]:
    """Turn the analysis into the numbered fact list the prompt is built from."""
    cards: list[FactCard] = []
    snapshot = analysis.latest
    currency = analysis.history.currency

    if snapshot is not None:
        for metric in (*HEADLINE_METRICS, *RATIO_METRICS):
            fact = snapshot.get(metric)
            if not fact.is_available:
                continue
            cards.append(
                _card(
                    len(cards),
                    label=f"{METRIC_LABELS.get(metric, metric.value)} {snapshot.period.label}",
                    value=format_metric(metric, fact, currency),
                    fact=fact,
                )
            )

    for metric, trend in analysis.trends.items():
        if trend.cagr is None or not trend.cagr.is_available:
            continue
        cards.append(
            _card(
                len(cards),
                label=f"Entwicklung {METRIC_LABELS.get(metric, metric.value)}",
                value=(
                    f"{TREND_LABELS.get(trend.direction.value, trend.direction.value)}, "
                    f"CAGR {trend.cagr.value:.1%} ueber {trend.periods} Perioden"
                ),
                fact=trend.cagr,
            )
        )

    for label, fact in _valuation_facts(analysis):
        if fact.is_available:
            cards.append(_card(len(cards), label=label, value=fact.display(), fact=fact))

    return cards


def _card(index: int, *, label: str, value: str, fact: NumericFact) -> FactCard:
    return FactCard(id=f"F{index + 1}", label=label, value=value, sources=tuple(fact.sources))


def _valuation_facts(analysis: CompanyAnalysis) -> list[tuple[str, NumericFact]]:
    facts: list[tuple[str, NumericFact]] = [
        ("Rechnerischer Wert je Aktie unter den Modellannahmen", analysis.valuation.value_per_share)
    ]
    if analysis.multiples is not None:
        facts.extend(
            [
                ("Kurs-Gewinn-Verhaeltnis", analysis.multiples.price_earnings),
                ("Kurs-Buchwert-Verhaeltnis", analysis.multiples.price_book),
                ("EV/EBITDA", analysis.multiples.ev_ebitda),
            ]
        )
    return facts


def _messages(
    analysis: CompanyAnalysis, cards: list[FactCard], *, max_notes: int
) -> list[LlmMessage]:
    snapshot = analysis.latest
    user = (
        (PROMPTS / "research_user.md")
        .read_text(encoding="utf-8")
        .format(
            company=analysis.company.name,
            ticker=analysis.ticker,
            period=snapshot.period.label if snapshot else "unbekannt",
            currency=analysis.history.currency or "unbekannt",
            facts="\n".join(card.render() for card in cards),
            max_notes=max_notes,
        )
    )
    return [
        LlmMessage(
            role=Role.SYSTEM, content=(PROMPTS / "research_system.md").read_text(encoding="utf-8")
        ),
        LlmMessage(role=Role.USER, content=user),
    ]


def _validate(
    output: ResearchOutput, cards: list[FactCard], *, model: str, max_notes: int
) -> ResearchNotes:
    by_id = {card.id: card for card in cards}
    notes: list[ResearchNote] = []
    rejected = 0

    for finding in output.findings:
        statement = finding.statement.strip()
        cited = [by_id[fact_id] for fact_id in dict.fromkeys(finding.fact_ids) if fact_id in by_id]
        reason = _rejection_reason(statement, finding, cited)
        if reason is not None:
            rejected += 1
            logger.info("research.statement_rejected", reason=reason, statement=statement[:120])
            continue
        notes.append(
            ResearchNote(
                category=finding.category,
                statement=statement,
                fact_ids=tuple(card.id for card in cited),
                sources=_merge_sources(cited),
            )
        )
        if len(notes) == max_notes:
            break

    warnings: list[str] = []
    if rejected:
        warnings.append(
            f"{rejected} Aussage(n) des Sprachmodells wurden verworfen, "
            "weil sie nicht durch die uebergebenen Fakten gedeckt waren."
        )
    return ResearchNotes(
        model=model,
        notes=tuple(notes),
        open_questions=tuple(q.strip() for q in output.open_questions if q.strip()),
        warnings=tuple(warnings),
        rejected=rejected,
    )


def _rejection_reason(
    statement: str, finding: ResearchFinding, cited: list[FactCard]
) -> str | None:
    if not statement:
        return "empty statement"
    if len(statement) > MAX_STATEMENT_CHARS:
        return "statement too long"
    if not finding.fact_ids:
        return "no citation"
    if len(cited) < len(set(finding.fact_ids)):
        return "cites at least one unknown fact"
    allowed: set[str] = set()
    for card in cited:
        allowed |= card.numbers()
    unsupported = _numbers(_FACT_REFERENCE.sub(" ", statement)) - allowed
    if unsupported:
        return f"unsupported numbers: {sorted(unsupported)}"
    return None


def _merge_sources(cards: list[FactCard]) -> tuple[SourceRef, ...]:
    merged: list[SourceRef] = []
    for card in cards:
        for source in card.sources:
            if source not in merged:
                merged.append(source)
    return tuple(merged)


def _numbers(text: str) -> set[str]:
    """Numeric tokens in a normalised form, so formatting differences do not matter."""
    tokens: set[str] = set()
    for raw in _NUMBER.findall(text):
        cleaned = _THOUSANDS.sub("", raw.rstrip(".,")).replace(",", ".")
        if cleaned:
            tokens.add(cleaned)
    return tokens
