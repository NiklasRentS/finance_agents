"""Tests for the provenance primitives that guard against hallucinated data."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.facts import (
    NOT_AVAILABLE,
    Confidence,
    ConflictedFact,
    Fact,
    FactKind,
    Period,
    PeriodType,
    SourceRef,
    SourceTier,
)

SEC_SOURCE = SourceRef(
    provider="SEC EDGAR",
    tier=SourceTier.REGULATORY_FILING,
    title="Apple Inc. 10-K FY2024",
    url="https://www.sec.gov/example",
    document_id="0000320193-24-000123",
    locator="us-gaap:Revenues",
    published_at=date(2024, 11, 1),
)


class TestFactSourceRequirement:
    def test_reported_value_without_source_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="no source"):
            Fact[float](value=391_035_000_000.0, kind=FactKind.REPORTED, unit="USD")

    def test_estimate_value_without_source_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="no source"):
            Fact[float](value=1.5, kind=FactKind.ESTIMATE)

    def test_reported_value_with_source_is_accepted(self) -> None:
        fact = Fact[float](
            value=391_035_000_000.0,
            unit="USD",
            kind=FactKind.REPORTED,
            confidence=Confidence.HIGH,
            sources=[SEC_SOURCE],
        )
        assert fact.is_available
        assert fact.value == pytest.approx(391_035_000_000.0)

    def test_missing_value_never_requires_a_source(self) -> None:
        fact = Fact[float](value=None, kind=FactKind.REPORTED)
        assert not fact.is_available

    def test_derived_value_needs_no_source(self) -> None:
        fact = Fact.derived(0.46, unit="ratio")
        assert fact.kind is FactKind.DERIVED
        assert fact.is_available


class TestFactRendering:
    def test_missing_value_renders_as_not_available(self) -> None:
        assert Fact[float].not_available(unit="USD").display() == NOT_AVAILABLE

    def test_assumption_is_always_flagged(self) -> None:
        fact = Fact[float].assumption(
            0.08,
            unit="ratio",
            rationale="WACC derived from CAPM with 10y treasury",
        )
        assert fact.is_assumption
        assert "[ASSUMPTION]" in fact.display()
        assert fact.sources, "assumptions must still carry the model source marker"

    def test_low_confidence_is_surfaced(self) -> None:
        fact = Fact.derived(12.5, unit="USD", confidence=Confidence.LOW)
        assert "[LOW CONFIDENCE]" in fact.display()

    def test_numbers_are_thousand_separated(self) -> None:
        fact = Fact.derived(1234567.891, unit="USD")
        assert fact.display() == "1,234,567.89 USD"


class TestPeriod:
    def test_fiscal_year_label(self) -> None:
        period = Period.fiscal_year_of(2024)
        assert period.label == "FY2024"

    def test_quarter_label(self) -> None:
        period = Period(
            type=PeriodType.QUARTER,
            fiscal_year=2025,
            fiscal_quarter=3,
            end=date(2025, 6, 28),
        )
        assert period.label == "Q3 2025"

    def test_quarter_requires_quarter_number(self) -> None:
        with pytest.raises(ValidationError, match="fiscal_quarter"):
            Period(type=PeriodType.QUARTER, fiscal_year=2025, end=date(2025, 6, 28))

    def test_start_after_end_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be after"):
            Period(
                type=PeriodType.FISCAL_YEAR,
                start=date(2025, 1, 1),
                end=date(2024, 1, 1),
            )


class TestConflictedFact:
    def test_conflict_keeps_both_values_and_stays_low_confidence(self) -> None:
        other = SourceRef(provider="Provider X", tier=SourceTier.FINANCIAL_DATA_PROVIDER)
        conflict = ConflictedFact[float](
            metric="revenue",
            period=Period.fiscal_year_of(2024),
            candidates=[
                Fact[float](
                    value=391_035.0,
                    unit="USDm",
                    kind=FactKind.REPORTED,
                    sources=[SEC_SOURCE],
                ),
                Fact[float](
                    value=390_000.0,
                    unit="USDm",
                    kind=FactKind.REPORTED,
                    sources=[other],
                ),
            ],
            likely_reason="Different fiscal year cut-off",
        )
        rendered = conflict.display()
        assert "391,035.00" in rendered
        assert "390,000.00" in rendered
        assert conflict.confidence is Confidence.LOW

    def test_single_candidate_is_not_a_conflict(self) -> None:
        with pytest.raises(ValidationError):
            ConflictedFact[float](
                metric="revenue",
                candidates=[Fact.derived(1.0)],
            )
