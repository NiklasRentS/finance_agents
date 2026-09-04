"""Core provenance primitives.

Every numeric or factual value in this system is wrapped in a :class:`Fact`.
A bare ``float`` never travels through the domain, because a number without a
source cannot be distinguished from a hallucination.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

NOT_AVAILABLE = "DATA NOT AVAILABLE"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class FactKind(StrEnum):
    """Where a value came from. Drives report labelling and validation."""

    REPORTED = "REPORTED"
    """Taken verbatim from a primary document (filing, report)."""

    DERIVED = "DERIVED"
    """Deterministically computed by this system from REPORTED inputs."""

    ESTIMATE = "ESTIMATE"
    """Third-party forecast or company guidance."""

    ASSUMPTION = "ASSUMPTION"
    """Model input chosen by us. Must always be surfaced to the user."""


class SourceTier(IntEnum):
    """Source priority. Lower value wins when reconciling conflicts."""

    COMPANY_REPORT = 1
    REGULATORY_FILING = 2
    INVESTOR_RELATIONS = 3
    COMPANY_ANNOUNCEMENT = 4
    FINANCIAL_DATA_PROVIDER = 5
    NEWS = 6
    OTHER = 7
    MODEL_ASSUMPTION = 8


class PeriodType(StrEnum):
    FISCAL_YEAR = "FY"
    QUARTER = "Q"
    TTM = "TTM"
    POINT_IN_TIME = "PIT"


class Period(BaseModel):
    """A reporting period. ``end`` is the anchor used for all sorting."""

    model_config = ConfigDict(frozen=True)

    type: PeriodType
    end: date
    start: date | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def _check_ordering(self) -> Period:
        if self.start is not None and self.start > self.end:
            raise ValueError("Period.start must not be after Period.end")
        if self.type is PeriodType.QUARTER and self.fiscal_quarter is None:
            raise ValueError("Quarterly periods require a fiscal_quarter")
        return self

    @property
    def label(self) -> str:
        match self.type:
            case PeriodType.FISCAL_YEAR:
                return f"FY{self.fiscal_year or self.end.year}"
            case PeriodType.QUARTER:
                return f"Q{self.fiscal_quarter} {self.fiscal_year or self.end.year}"
            case PeriodType.TTM:
                return f"TTM to {self.end.isoformat()}"
            case PeriodType.POINT_IN_TIME:
                return self.end.isoformat()

    @classmethod
    def fiscal_year_of(cls, year: int, end: date | None = None) -> Period:
        return cls(
            type=PeriodType.FISCAL_YEAR,
            fiscal_year=year,
            end=end or date(year, 12, 31),
        )


class SourceRef(BaseModel):
    """Pointer to where a value was obtained."""

    model_config = ConfigDict(frozen=True)

    provider: str
    tier: SourceTier
    title: str | None = None
    url: str | None = None
    document_id: str | None = None
    """Stable document identifier, e.g. an SEC accession number."""

    locator: str | None = None
    """Position inside the document, e.g. an XBRL tag or section heading."""

    published_at: date | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def citation(self) -> str:
        parts = [self.provider]
        if self.title:
            parts.append(self.title)
        if self.published_at:
            parts.append(self.published_at.isoformat())
        if self.url:
            parts.append(self.url)
        return " | ".join(parts)


MODEL_ASSUMPTION_SOURCE = SourceRef(
    provider="finance_agents/model",
    tier=SourceTier.MODEL_ASSUMPTION,
    title="Internal model assumption",
)


class Fact[T](BaseModel):
    """A single value together with everything needed to audit it."""

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    unit: str | None = None
    period: Period | None = None
    kind: FactKind = FactKind.REPORTED
    confidence: Confidence = Confidence.UNKNOWN
    sources: list[SourceRef] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _require_source_for_external_values(self) -> Fact[T]:
        """A present value of external origin must be traceable."""
        needs_source = self.kind in (FactKind.REPORTED, FactKind.ESTIMATE)
        if self.value is not None and needs_source and not self.sources:
            raise ValueError(
                f"Fact of kind {self.kind} carries a value but no source. "
                "Every reported or estimated value must be traceable."
            )
        return self

    @property
    def is_available(self) -> bool:
        return self.value is not None

    @property
    def is_assumption(self) -> bool:
        return self.kind is FactKind.ASSUMPTION

    def display(self, precision: int = 2) -> str:
        """Human readable rendering that never invents a value."""
        if self.value is None:
            return NOT_AVAILABLE
        text = f"{self.value:,.{precision}f}" if isinstance(self.value, float) else str(self.value)
        if self.unit and self.unit != "ratio":
            text = f"{text} {self.unit}"
        if self.kind is FactKind.ASSUMPTION:
            text = f"{text} [ASSUMPTION]"
        if self.confidence is Confidence.LOW:
            text = f"{text} [LOW CONFIDENCE]"
        return text

    @classmethod
    def not_available(
        cls,
        *,
        unit: str | None = None,
        period: Period | None = None,
        note: str | None = None,
    ) -> Fact[T]:
        return cls(
            value=None,
            unit=unit,
            period=period,
            kind=FactKind.DERIVED,
            confidence=Confidence.UNKNOWN,
            note=note,
        )

    @classmethod
    def assumption(
        cls,
        value: T,
        *,
        unit: str | None = None,
        rationale: str,
        confidence: Confidence = Confidence.MEDIUM,
        period: Period | None = None,
    ) -> Fact[T]:
        """Create an explicitly flagged model input."""
        return cls(
            value=value,
            unit=unit,
            period=period,
            kind=FactKind.ASSUMPTION,
            confidence=confidence,
            sources=[MODEL_ASSUMPTION_SOURCE],
            note=rationale,
        )

    @classmethod
    def derived(
        cls,
        value: T | None,
        *,
        unit: str | None = None,
        period: Period | None = None,
        sources: list[SourceRef] | None = None,
        confidence: Confidence = Confidence.MEDIUM,
        note: str | None = None,
    ) -> Fact[T]:
        """Create a value computed by this system from other facts."""
        return cls(
            value=value,
            unit=unit,
            period=period,
            kind=FactKind.DERIVED,
            confidence=confidence,
            sources=sources or [],
            note=note,
        )


class ConflictedFact[T](BaseModel):
    """Two or more sources disagree beyond tolerance.

    The system deliberately refuses to pick a winner here. Both values are
    carried into the report so the reader can judge.
    """

    model_config = ConfigDict(frozen=True)

    metric: str
    period: Period | None = None
    candidates: list[Fact[T]] = Field(min_length=2)
    likely_reason: str | None = None

    @property
    def confidence(self) -> Confidence:
        return Confidence.LOW

    def display(self) -> str:
        rendered = " vs. ".join(c.display() for c in self.candidates)
        suffix = f" ({self.likely_reason})" if self.likely_reason else ""
        return f"CONFLICT: {rendered}{suffix} [LOW CONFIDENCE]"
