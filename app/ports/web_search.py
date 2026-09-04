"""Port for open web search used by the research agent."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

from app.domain.facts import SourceRef


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    snippet: str | None = None
    source: SourceRef | None = None


class WebSearchProvider(ABC):
    name: str

    @abstractmethod
    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        """Return search results ordered by relevance."""

    @abstractmethod
    def fetch_page_text(self, url: str) -> str:
        """Return the readable text content of a page."""
