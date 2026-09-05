"""Read-only broker provider port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.broker import BrokerSnapshot


class BrokerProvider(ABC):
    """Read imported broker data without exposing trading capabilities."""

    name: str

    @abstractmethod
    def import_snapshot(self, source: Path) -> BrokerSnapshot:
        """Read one local broker export into the normalized domain model."""
