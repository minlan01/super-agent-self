"""Anthropic Claude Provider — native Messages API via httpx.

Uses httpx directly (no anthropic SDK) to stay consistent with
DeepSeekProvider's pattern. Handles:
- System message separation
- Extended thinking (budget_tokens)
- Prompt caching (cache_control)
- JSON mode via prompt engineering + response validation
- Streaming SSE
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from packages.llm_gateway.base import BaseLLMProvider, LLMMessage, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider using the native Messages API."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", _DEFAULT_BASE_URL)
        self.model = config.get("model", "claude-sonnet-4-20250514")
        env_keys = config.get("env_keys", [])
        if env_keys:
            self.api_key = next((os.environ.get(k, "") for k in env_keys if os.environ.get(k)), "")
        else:
            self.api_key = os.environ.get(config.get("env_key", "ANTHROPIC_API_KEY"), "")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.1)
        self.thinking_config = config.get("thinking", {})

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
        """Split system messages from conversation messages.

        Anthropic requires system as a separate top-level parameter.
        Returns (system_text, messages_list).
        """
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
                continue

            content: list[dict[str, Any]] = [{"type": "text", "text": msg.content}]

            # Add cache_control hint if present
            if msg.cache_control:
                content[0]["cache_control"] = msg.cache_control

            # Add thinking content if present (for multi-turn with thinking)
            if msg.thinking:
                content.insert(0, {"type": "thinking", "thinking": msg.thinking})

            converted.append({"role": msg.role, "content": content})

        system_text = "\n\n".join(system_parts)
        return system_text, converted

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _build_body(
        self,
        messages: list[LLMMessage],
        *,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        system_text, converted = self._convert_messages(messages)

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
            "messages": converted,
        }

        if system_text:
            body["system"] = system_text

        if self.thinking_config.get("enabled"):
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_config.get("budget_tokens", 10000),
            }
        elif not json_mode:
            body["temperature"] = kwargs.pop("temperature", self.temperature)

        return body

    async def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        """Send a request to the Anthropic Messages API."""
        client = await self._get_client()
        url = f"{self.base_url}/messages"
        resp = await client.post(url, headers=self._build_headers(), json=body)

        if resp.status_code == 401:
            raise RuntimeError(f"Anthropic auth failed: {resp.text[:200]}")
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 60))
            raise _RateLimitError(retry_after)
        if resp.status_code >= 500:
            raise RuntimeError(f"Anthropic server error ({resp.status_code}): {resp.text[:200]}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Anthropic API error ({resp.status_code}): {resp.text[:200]}")

        return resp.json()

    def _extract_text(self, data: dict[str, Any]) -> str:
        """Extract text content from Anthropic response blocks."""
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        return "\n".join(text_parts)

    def _extract_thinking(self, data: dict[str, Any]) -> str | None:
        """Extract thinking content from response blocks."""
        content_blocks = data.get("content", [])
        thinking_parts: list[str] = []
        for block in content_blocks:
            if block.get("type") == "thinking":
                thinking_parts.append(block.get("thinking", ""))
        return "\n".join(thinking_parts) if thinking_parts else None

    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        body = self._build_body(messages, **kwargs)
        data = await self._request(body)

        content = self._extract_text(data)
        thinking = self._extract_thinking(data)
        usage = data.get("usage", {})
        usage_int = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
        }

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            provider="anthropic",
            usage=usage_int,
            raw=data,
            thinking_content=thinking,
        )

    async def generate_json(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        # Anthropic doesn't have native JSON mode — use prompt engineering
        json_messages = list(messages)
        last = json_messages[-1] if json_messages else None
        if last and last.role == "user":
            json_messages[-1] = LLMMessage(
                role="user",
                content=last.content + "\n\nRespond with valid JSON only.",
            )
        else:
            json_messages.append(LLMMessage(role="user", content="Respond with valid JSON only."))

        response = await self.generate(json_messages, **kwargs)

        # Fallback JSON extraction
        if response.content and not response.content.strip().startswith(("{", "[")):
            json_match = re.search(r"[\{\[][\s\S]*[\}\]]", response.content)
            if json_match:
                response.content = json_match.group(0)
                logger.warning("Extracted JSON from non-JSON Anthropic response")
            else:
                logger.warning("Anthropic response does not contain valid JSON")

        return response

    async def stream(self, messages: list[LLMMessage], **kwargs: Any) -> AsyncIterator[LLMStreamChunk]:
        client = await self._get_client()
        body = self._build_body(messages, **kwargs)
        url = f"{self.base_url}/messages"
        body["stream"] = True

        async with client.stream("POST", url, headers=self._build_headers(), json=body) as resp:
            if resp.status_code >= 400:
                error_text = await resp.aread()
                yield LLMStreamChunk(delta=f"Error: {error_text.decode()[:200]}", finished=True)
                return

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    yield LLMStreamChunk(delta="", model=self.model, provider="anthropic", finished=True)
                    return

                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield LLMStreamChunk(
                            delta=delta.get("text", ""),
                            model=self.model,
                            provider="anthropic",
                        )
                elif event_type == "message_stop":
                    yield LLMStreamChunk(delta="", model=self.model, provider="anthropic", finished=True)
                    return


class _RateLimitError(RuntimeError):
    """Raised when Anthropic returns HTTP 429 with a Retry-After header."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited — retry after {retry_after:.0f}s")
