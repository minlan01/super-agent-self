"""Abstract base provider for LLM Gateway."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str
    thinking: str | None = None  # Anthropic extended thinking content
    cache_control: dict[str, Any] | None = None  # Anthropic prompt caching hint


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    provider: str = ""
    usage: dict[str, int] = field(default_factory=dict)  # {"prompt_tokens": ..., "completion_tokens": ...}
    raw: Any = None
    thinking_content: str | None = None  # Extracted thinking content (Claude)
    cost_estimate: float | None = None  # Estimated USD cost for this request


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming response."""
    delta: str  # incremental text content
    model: str = ""
    provider: str = ""
    finished: bool = False


@dataclass
class ProviderHealth:
    """Tracks health state for a single LLM provider."""
    provider_name: str
    consecutive_failures: int = 0
    last_failure_time: float | None = None
    last_failure_reason: str | None = None
    rate_limit_reset_at: float | None = None
    total_requests: int = 0
    total_failures: int = 0
    max_consecutive_failures: int = 3
    circuit_open_until: float | None = None
    circuit_cooldown_seconds: float = 60.0

    def is_healthy(self) -> bool:
        """Return True if provider is considered healthy.

        Implements a circuit-breaker pattern:
        - Closed (healthy): consecutive_failures < threshold
        - Open (unhealthy): consecutive_failures >= threshold, within cooldown
        - Half-open: cooldown expired, allow one probe request
        """
        if self.rate_limit_reset_at is not None and time.time() < self.rate_limit_reset_at:
            return False
        if self.consecutive_failures < self.max_consecutive_failures:
            return True
        if self.circuit_open_until is not None and time.time() < self.circuit_open_until:
            return False
        if self.circuit_open_until is None:
            return False
        return True


@dataclass
class CostRecord:
    """A single cost tracking record."""
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    timestamp: float = field(default_factory=time.time)


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.name: str = config.get("name", "unknown")
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._timeout: int = config.get("timeout", 120)

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=self._timeout,
                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                )
        return self._client

    @abstractmethod
    async def generate(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def generate_json(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Generate a JSON response from the LLM."""
        ...

    async def close(self) -> None:
        """Close the httpx client. Subclasses may override for additional cleanup."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[LLMStreamChunk]:
        """Stream a response from the LLM. Default: generate then yield single chunk."""
        response = await self.generate(messages, **kwargs)
        yield LLMStreamChunk(
            delta=response.content,
            model=response.model,
            provider=response.provider,
            finished=True,
        )
