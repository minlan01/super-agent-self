"""Google Gemini Provider — Gemini REST API via httpx.

Uses httpx to call Google's generativelanguage.googleapis.com endpoint.
Handles:
- Message format conversion (role → user/model, content → parts)
- System instruction extraction
- JSON mode via responseMimeType
- Streaming via streamGenerateContent
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

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider using the REST API."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", _DEFAULT_BASE_URL)
        self.model = config.get("model", "gemini-2.0-flash")
        env_keys = config.get("env_keys", [])
        if env_keys:
            self.api_key = next((os.environ.get(k, "") for k in env_keys if os.environ.get(k)), "")
        else:
            self.api_key = os.environ.get(config.get("env_key", "GEMINI_API_KEY"), "")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.1)

    def _convert_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert messages to Gemini format.

        Returns (system_instruction, contents).
        Gemini uses "user" and "model" roles (not "assistant").
        System instructions go in a separate field.
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
                continue

            role = "model" if msg.role == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}],
            })

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    def _build_body(
        self,
        messages: list[LLMMessage],
        *,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        system_instruction, contents = self._convert_messages(messages)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": kwargs.pop("max_tokens", self.max_tokens),
                "temperature": kwargs.pop("temperature", self.temperature),
            },
        }

        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        return body

    def _build_url(self, *, stream: bool = False) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        return f"{self.base_url}/models/{self.model}:{action}"

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    async def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        client = await self._get_client()
        body = self._build_body(messages, **kwargs)
        url = self._build_url()
        headers = self._build_headers()
        logger.debug("GeminiProvider requesting %s with %d messages", url, len(messages))
        resp = await client.post(url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code == 401:
            raise RuntimeError(f"Gemini auth failed: {resp.text[:200]}")
        if resp.status_code == 429:
            raise RuntimeError(f"Gemini rate limited: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini API error ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        candidates = data.get("candidates", [])
        content = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            content = "\n".join(p.get("text", "") for p in parts if "text" in p)

        usage_meta = data.get("usageMetadata", {})
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
        }

        return LLMResponse(
            content=content,
            model=self.model,
            provider="gemini",
            usage=usage,
            raw=data,
        )

    async def generate_json(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        """Gemini supports native JSON mode via responseMimeType."""
        response = await self.generate(messages, json_mode=True, **kwargs)

        # Fallback JSON extraction
        if response.content and not response.content.strip().startswith(("{", "[")):
            json_match = re.search(r"[\{\[][\s\S]*[\}\]]", response.content)
            if json_match:
                response.content = json_match.group(0)
                logger.warning("Extracted JSON from non-JSON Gemini response")

        # Validate JSON is parseable
        try:
            json.loads(response.content)
        except json.JSONDecodeError:
            logger.warning("Gemini JSON response is not valid JSON")

        return response

    async def stream(self, messages: list[LLMMessage], **kwargs: Any) -> AsyncIterator[LLMStreamChunk]:
        client = await self._get_client()
        body = self._build_body(messages, **kwargs)
        url = self._build_url(stream=True)

        async with client.stream("POST", url, json=body, headers=self._build_headers()) as resp:
            if resp.status_code >= 400:
                error_text = await resp.aread()
                yield LLMStreamChunk(delta=f"Error: {error_text.decode()[:200]}", finished=True)
                return

            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                # Gemini streaming returns JSON arrays or objects
                try:
                    # May be prefixed with data:
                    payload = line.strip()
                    if payload.startswith("data: "):
                        payload = payload[6:]
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                candidates = chunk.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            yield LLMStreamChunk(
                                delta=part["text"],
                                model=self.model,
                                provider="gemini",
                            )

                # Check finish reason
                if candidates:
                    finish = candidates[0].get("finishReason")
                    if finish and finish != "STOP":
                        pass  # Continue generating
                    elif finish == "STOP":
                        yield LLMStreamChunk(delta="", model=self.model, provider="gemini", finished=True)
                        return
