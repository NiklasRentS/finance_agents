"""Port for language model access.

LLMs interpret text. They never produce figures used in calculations, so this
port intentionally exposes no numeric helpers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LlmMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class LlmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


class LlmClient(ABC):
    name: str

    @abstractmethod
    def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        """Run a completion. When ``json_schema`` is set the model must return JSON."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the backend is reachable."""
