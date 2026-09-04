"""Port for macroeconomic inputs, primarily WACC components."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.facts import Fact


class MacroProvider(ABC):
    name: str

    @abstractmethod
    def get_risk_free_rate(self) -> Fact[float]:
        """Return the current long-term government bond yield as a decimal ratio."""

    @abstractmethod
    def get_series_latest(self, series_id: str) -> Fact[float]:
        """Return the latest observation of a macro series."""
