"""Ports for news and open web research."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.domain.company import Company
from app.domain.facts import SourceRef


class NewsItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    published_at: date | None = None
    summary: str | None = None
    publisher: str | None = None
    source: SourceRef | None = None


class NewsProvider(ABC):
    name: str

    @abstractmethod
    def get_news(
        self, company: Company, *, since: date | None = None, limit: int = 25
    ) -> list[NewsItem]:
        """Return news items newest first."""
