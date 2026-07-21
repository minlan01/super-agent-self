"""DeepSeek provider using OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from packages.llm_gateway.base import BaseLLMProvider, LLMMessage, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek LLM provider via OpenAI-compatible chat completions API."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.base_url: str = config.get("base_url", "https://api.deepseek.com/v1")
        self.model: str = config.get("model", "deepseek-chat")
        env_key: str = config.get("env_key", "DEEPSEEK_API_KEY")
        self.api_key: str | None = os.environ.get(env_key) or "local"
        self.max_tokens: int = config.get("max_tokens", 4096)
        self.temperature: float = config.get("temperature", 0.1)
        self.extra_body: dict[str, Any] = config.get("extra_body", {})
        self.name: str = config.get("name", "deepseek")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(
        self,
        messages: list[LLMMessage],
        *,
        json_mode: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.extra_body:
            body.update(self.extra_body)
        return body

    async def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        client = await self._get_client()
        try:
            resp = await client.post(
                url, headers=self._build_headers(), json=body
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise RuntimeError(
                    f"DeepSeek API key invalid or missing (HTTP {status})"
                ) from exc
            if status == 429:
                raise RuntimeError(
                    "DeepSeek rate limit exceeded (HTTP 429). Retry later."
                ) from exc
            raise RuntimeError(
                f"DeepSeek API error: HTTP {status} — {exc.response.text}"
            ) from exc
        except httpx.ConnectTimeout as exc:
            raise RuntimeError(
                f"DeepSeek connection timeout after {self.timeout}s"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"DeepSeek request failed: {exc}"
            ) from exc

    @staticmethod
    def _parse_usage(raw_usage: Any) -> dict[str, int]:
        if not raw_usage or not isinstance(raw_usage, dict):
            return {}
        return {
            "prompt_tokens": raw_usage.get("prompt_tokens", 0),
            "completion_tokens": raw_usage.get("completion_tokens", 0),
        }

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse a standard chat completion response into LLMResponse."""
        choices = data.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            raise RuntimeError(
                f"DeepSeek API returned no choices: {json.dumps(data)[:200]}"
            )
        choice = choices[0]
        msg = choice.get("message")
        if not msg or not isinstance(msg, dict):
            raise RuntimeError(
                f"DeepSeek API returned invalid message in choice: {json.dumps(choice)[:200]}"
            )
        content = msg.get("content", "")
        usage = self._parse_usage(data.get("usage"))

        logger.debug(
            "%s response: model=%s, tokens=%s",
            self.name, data.get("model", self.model), usage,
        )
        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            provider=self.name,
            usage=usage,
            raw=data,
        )

    async def generate(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Standard chat completion."""
        body = self._build_body(messages, **kwargs)
        data = await self._request(body)
        return self._parse_response(data)

    async def generate_json(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Chat completion with JSON response format."""
        msgs = list(messages)
        if msgs and msgs[-1].role == "user":
            last_content = msgs[-1].content
            if "json" not in last_content.lower():
                msgs[-1] = LLMMessage(
                    role="user",
                    content=f"{last_content}\n\nRespond with valid JSON only.",
                )

        body = self._build_body(msgs, json_mode=True, **kwargs)
        data = await self._request(body)
        response = self._parse_response(data)

        try:
            json.loads(response.content)
        except json.JSONDecodeError:
            logger.warning(
                "DeepSeek JSON response was not valid JSON, attempting extraction"
            )
            start = response.content.find("{")
            end = response.content.rfind("}")
            if start != -1 and end != -1 and end > start:
                extracted = response.content[start : end + 1]
                try:
                    json.loads(extracted)
                    response.content = extracted
                except json.JSONDecodeError:
                    logger.error("Could not extract valid JSON from response")

        return response

    async def stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[LLMStreamChunk]:
        """Stream a response via SSE from the OpenAI-compatible API."""
        body = self._build_body(messages, **kwargs)
        body["stream"] = True
        url = f"{self.base_url}/chat/completions"
        client = await self._get_client()

        try:
            async with client.stream(
                "POST", url, headers=self._build_headers(), json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield LLMStreamChunk(delta="", model=self.model, provider=self.name, finished=True)
                        return
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield LLMStreamChunk(
                                delta=content,
                                model=chunk.get("model", self.model),
                                provider=self.name,
                            )
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            raise RuntimeError(f"Streaming failed: {exc}") from exc
