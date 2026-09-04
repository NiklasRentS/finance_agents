"""Adapter for a locally running Ollama server.

The model never contributes figures: it receives facts that are already sourced
and is asked to phrase observations about them. Enforcement of that rule lives
in the research agent, which validates every sentence the model returns.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import Settings
from app.infra.logging import get_logger
from app.ports.exceptions import ProviderUnavailableError
from app.ports.llm import LlmClient, LlmMessage, LlmResponse

logger = get_logger(__name__)

CHAT_PATH = "/api/chat"
TAGS_PATH = "/api/tags"


class OllamaClient(LlmClient):
    """Talks to the Ollama HTTP API."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float,
        temperature: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    @classmethod
    def build(cls, settings: Settings) -> OllamaClient:
        return cls(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=float(settings.llm_timeout_seconds),
            temperature=settings.llm_temperature,
        )

    def close(self) -> None:
        self._client.close()

    def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": message.role.value, "content": message.content} for message in messages
            ],
            "stream": False,
            "options": {"temperature": self._temperature if temperature is None else temperature},
        }
        if json_schema is not None:
            payload["format"] = json_schema

        try:
            response = self._client.post(CHAT_PATH, json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"chat request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderUnavailableError(self.name, f"malformed response: {exc}") from exc

        content = body.get("message", {}).get("content", "")
        logger.debug(
            "ollama.completed",
            model=body.get("model", self.model),
            tokens_in=body.get("prompt_eval_count", 0),
            tokens_out=body.get("eval_count", 0),
        )
        return LlmResponse(
            text=content if isinstance(content, str) else "",
            model=str(body.get("model", self.model)),
            tokens_in=int(body.get("prompt_eval_count", 0) or 0),
            tokens_out=int(body.get("eval_count", 0) or 0),
        )

    def is_available(self) -> bool:
        """True only when the server answers and the configured model is present."""
        try:
            response = self._client.get(TAGS_PATH)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("ollama.unreachable", error=str(exc))
            return False

        installed = {
            str(entry.get("name", ""))
            for entry in body.get("models", [])
            if isinstance(entry, dict)
        }
        if self.model in installed:
            return True
        logger.info("ollama.model_missing", model=self.model, installed=sorted(installed))
        return False
