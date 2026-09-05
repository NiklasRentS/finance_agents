"""Versioned local fixture adapter for Trade Republic portfolio data.

This is deliberately not a parser for a real Trade Republic export. Until an
anonymized real export is available, the adapter accepts only the documented
``finance-agents-trade-republic-export-v1`` interchange format.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.broker import BrokerSnapshot
from app.ports.broker import BrokerProvider


class BrokerImportError(ValueError):
    """The local broker export is malformed or uses an unsupported format."""


class TradeRepublicExportProvider(BrokerProvider):
    name = "trade_republic_export"
    FORMAT = "finance-agents-trade-republic-export-v1"

    def import_snapshot(self, source: Path) -> BrokerSnapshot:
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrokerImportError(f"could not read JSON export: {source}") from exc
        if not isinstance(payload, dict) or payload.get("format") != self.FORMAT:
            raise BrokerImportError(
                f"unsupported export format; expected {self.FORMAT!r}"
            )
        try:
            return BrokerSnapshot.model_validate(payload["data"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise BrokerImportError("export data does not match the v1 schema") from exc