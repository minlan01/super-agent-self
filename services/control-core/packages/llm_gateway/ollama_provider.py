"""Ollama Provider — local LLM via Ollama REST API.

Uses httpx to call Ollama's /api/chat endpoint. No API key required.
Supports native JSON mode via format="json".
Streaming uses NDJSON format.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from packages.llm_gateway.base import BaseLLMProvider, LLMMessage, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(BaseLLMProvider):
    """Ollama local model provider — no API key required."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", _DEFAULT_BASE_URL)
        self.model = config.get("model", "qwen3:8b")
        self.max_tokens = config.get("max_tokens", 2048)
        self.temperature = config.get("temperature", 0.1)

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
        """Convert LLMMessage list to Ollama format.

        Ollama uses the same OpenAI-style role/content format.
        """
        result: list[dict[str, str]] = []
        for msg in messages:
            result.append({"role": msg.role, "content": msg.content})
        return result

    def _build_body(
        self,
        messages: list[LLMMessage],
        *,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "stream": False,
            "options": {
                "num_predict": kwargs.pop("max_tokens", self.max_tokens),
                "temperature": kwargs.pop("temperature", self.temperature),
            },
        }
        if json_mode:
            body["format"] = "json"
        return body

    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        client = await self._get_client()
        body = self._build_body(messages, **kwargs)
        url = f"{self.base_url}/api/chat"

        resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"Ollama error ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        message = data.get("message", {})
        content = message.get("content", "")

        # Extract usage if available (Ollama may not always provide this)
        usage = {}
        if "prompt_eval_count" in data:
            usage["prompt_tokens"] = data["prompt_eval_count"]
        if "eval_count" in data:
            usage["completion_tokens"] = data["eval_count"]

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            provider="ollama",
            usage=usage,
            raw=data,
        )

    async def generate_json(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        """Ollama supports native JSON mode via format='json'."""
        return await self.generate(messages, json_mode=True, **kwargs)

    async def stream(self, messages: list[LLMMessage], **kwargs: Any) -> AsyncIterator[LLMStreamChunk]:
        client = await self._get_client()
        body = self._build_body(messages, **kwargs)
        body["stream"] = True
        url = f"{self.base_url}/api/chat"

        async with client.stream("POST", url, json=body) as resp:
            if resp.status_code >= 400:
                error_text = await resp.aread()
                yield LLMStreamChunk(delta=f"Error: {error_text.decode()[:200]}", finished=True)
                return

            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = chunk.get("message", {})
                delta = message.get("content", "")
                done = chunk.get("done", False)

                if delta:
                    yield LLMStreamChunk(
                        delta=delta,
                        model=self.model,
                        provider="ollama",
                    )
                if done:
                    yield LLMStreamChunk(delta="", model=self.model, provider="ollama", finished=True)
                    return
