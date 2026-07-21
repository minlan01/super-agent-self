"""Provider router — loads config, instantiates providers, and routes LLM requests.

Supports:
- Direct dispatch: router.generate(messages, provider="deepseek")
- Failover dispatch: router.generate(messages, chain="default")
- Credential pooling per provider
- Health tracking for failover decisions
- Cost estimation per request
- Exponential backoff with jitter on retries
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

import yaml

from packages.llm_gateway.anthropic_provider import AnthropicProvider
from packages.llm_gateway.anthropic_provider import _RateLimitError as AnthropicRateLimitError
from packages.llm_gateway.base import BaseLLMProvider, LLMMessage, LLMResponse, LLMStreamChunk
from packages.llm_gateway.cost_tracker import CostTracker
from packages.llm_gateway.credential_pool import CredentialPool
from packages.llm_gateway.deepseek_provider import DeepSeekProvider
from packages.llm_gateway.error_classifier import ErrorCategory, classify_error
from packages.llm_gateway.gemini_provider import GeminiProvider
from packages.llm_gateway.health_tracker import ProviderHealthTracker
from packages.llm_gateway.mock_provider import MockProvider
from packages.llm_gateway.ollama_provider import OllamaProvider
from packages.llm_gateway.smart_router import SmartModelRouter

logger = logging.getLogger(__name__)

_PROVIDER_TYPES: dict[str, type[BaseLLMProvider]] = {
    "mock": MockProvider,
    "openai_compatible": DeepSeekProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
    "gemini": GeminiProvider,
}

_module_router: ProviderRouter | None = None
_module_router_lock = threading.Lock()


def get_module_router() -> ProviderRouter:
    """Module-level singleton accessor for ProviderRouter."""
    global _module_router
    with _module_router_lock:
        if _module_router is None:
            _module_router = ProviderRouter()
        return _module_router


class ProviderRouter:
    """Routes LLM requests to the appropriate provider based on config.

    Supports both direct dispatch and failover chains.
    """

    def __init__(self, config_path: str = "configs/models.yaml") -> None:
        self.config_path = config_path
        self.providers: dict[str, BaseLLMProvider] = {}
        self.default_provider: str = "mock"
        self.credential_pools: dict[str, CredentialPool] = {}
        self.health_tracker = ProviderHealthTracker()
        self.cost_tracker = CostTracker()
        self.smart_router = SmartModelRouter()
        self.failover_chains: dict[str, list[str]] = {}
        self._load_config()

    async def close(self) -> None:
        """Close all provider HTTP clients (httpx.AsyncClient)."""
        for name, provider in self.providers.items():
            try:
                if hasattr(provider, "close") and callable(provider.close):
                    await provider.close()
            except Exception as exc:
                logger.warning("Failed to close provider '%s': %s", name, exc)

    def _load_config(self) -> None:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("Config file not found at '%s', using defaults", self.config_path)
            cfg = {}

        providers_cfg = cfg.get("providers", {})
        defaults = cfg.get("defaults", {})
        failover_cfg = cfg.get("failover", {})

        # Env var override for default provider
        env_provider = os.environ.get("LLM_PROVIDER")
        self.default_provider = env_provider or defaults.get("provider", "mock")

        # Instantiate each configured provider
        for name, prov_cfg in providers_cfg.items():
            provider_type = prov_cfg.get("type")
            cls = _PROVIDER_TYPES.get(provider_type)
            if cls is None:
                logger.warning("Unknown provider type '%s' for '%s', skipping", provider_type, name)
                continue

            config = {**prov_cfg, "name": name}
            try:
                self.providers[name] = cls(config)
                logger.info("Initialized provider '%s' (%s)", name, provider_type)
            except Exception:
                logger.exception("Failed to initialize provider '%s'", name)

            # Set up credential pool for providers with API keys
            env_keys = prov_cfg.get("env_keys", [])
            env_key_single = prov_cfg.get("env_key", "")
            if env_keys:
                pool = CredentialPool.from_env_keys(env_keys)
                if not pool.is_empty():
                    self.credential_pools[name] = pool
            elif env_key_single:
                pool = CredentialPool.from_env_keys([env_key_single])
                if not pool.is_empty():
                    self.credential_pools[name] = pool

        # Load failover chains
        chains = failover_cfg.get("chains", {})
        for chain_name, provider_list in chains.items():
            self.failover_chains[chain_name] = provider_list
            logger.info("Failover chain '%s': %s", chain_name, provider_list)

        # Auto-generate default chain if not configured
        if "default" not in self.failover_chains:
            self.failover_chains["default"] = [self.default_provider, "mock"]

        # API key fallback checks
        for provider_name in ("deepseek", "openrouter", "openai"):
            if self.default_provider == provider_name:
                prov = self.providers.get(provider_name)
                if prov and not getattr(prov, "api_key", None):
                    logger.warning(
                        "%s API key not set — falling back to mock",
                        provider_name,
                    )
                    self.default_provider = "mock"

        # Ensure default provider exists
        if self.default_provider not in self.providers:
            if "mock" not in self.providers:
                self.providers["mock"] = MockProvider({"name": "mock"})
            logger.warning(
                "Default provider '%s' not available, falling back to mock",
                self.default_provider,
            )
            self.default_provider = "mock"

    def get_provider(self, name: str | None = None) -> BaseLLMProvider:
        """Get a provider by name, or return default."""
        key = name or self.default_provider
        if key not in self.providers:
            raise ValueError(f"Provider '{key}' not found. Available: {list(self.providers)}")
        return self.providers[key]

    # ── Direct dispatch (backward compatible) ────────────────────────────

    async def generate(
        self,
        messages: list[LLMMessage],
        provider: str | None = None,
        chain: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate using the specified provider or failover chain."""
        if chain is not None:
            return await self.generate_with_failover(messages, chain=chain, **kwargs)
        p = self.get_provider(provider)
        provider_name = provider or self.default_provider
        provider_type = type(p).__name__.replace("Provider", "").lower()
        if provider_type == "anthropic":
            messages = self._apply_caching_hints(messages)
        t0 = time.perf_counter()
        result = await p.generate(messages, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.smart_router.record_latency(provider_name, elapsed_ms)
        return result

    async def generate_json(
        self,
        messages: list[LLMMessage],
        provider: str | None = None,
        chain: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate JSON using the specified provider or failover chain."""
        if chain is not None:
            return await self.generate_with_failover(
                messages, chain=chain, json_mode=True, **kwargs
            )
        p = self.get_provider(provider)
        provider_name = provider or self.default_provider
        provider_type = type(p).__name__.replace("Provider", "").lower()
        if provider_type == "anthropic":
            messages = self._apply_caching_hints(messages)
        t0 = time.perf_counter()
        result = await p.generate_json(messages, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.smart_router.record_latency(provider_name, elapsed_ms)
        return result

    async def stream(
        self,
        messages: list[LLMMessage],
        provider: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream using the specified or default provider."""
        p = self.get_provider(provider)
        async for chunk in p.stream(messages, **kwargs):
            yield chunk

    # ── Failover dispatch ───────────────────────────────────────────────

    async def generate_with_failover(
        self,
        messages: list[LLMMessage],
        chain: str = "default",
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Try providers in failover chain order, with retry and backoff."""
        providers = self.failover_chains.get(chain) or [self.default_provider]
        tried: list[str] = []
        last_error: str = ""

        # Separate healthy and unhealthy for priority ordering
        healthy = [p for p in providers if self.health_tracker.is_healthy(p)]
        unhealthy = [p for p in providers if not self.health_tracker.is_healthy(p)]
        # Try healthy first; if all unhealthy, try them anyway
        ordered = healthy + unhealthy

        for name in ordered:
            if name not in self.providers:
                continue
            tried.append(name)
            try:
                result = await self._retry_with_backoff(
                    name, messages, json_mode=json_mode, **kwargs
                )
                self.health_tracker.record_success(name)
                self._record_cost(name, result)
                return result
            except Exception as e:
                self.health_tracker.record_failure(name, str(e))
                last_error = str(e)
                logger.warning("Provider '%s' failed: %s — trying next", name, last_error[:80])

        raise RuntimeError(
            f"All providers in chain '{chain}' failed. "
            f"Tried: {tried}. Last error: {last_error}"
        )

    async def _retry_with_backoff(
        self,
        provider_name: str,
        messages: list[LLMMessage],
        *,
        json_mode: bool = False,
        max_retries: int = 2,
        base_delay: float = 1.0,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call provider with exponential backoff + jitter retry.

        Uses the Error Classifier to determine whether an error is
        retryable and what delay to use.
        """
        provider = self.providers[provider_name]
        method = provider.generate_json if json_mode else provider.generate

        for attempt in range(max_retries + 1):
            try:
                result = await method(messages, **kwargs)
                return result
            except AnthropicRateLimitError as e:
                self.health_tracker.record_rate_limit(provider_name, time.time() + e.retry_after)
                if attempt == max_retries:
                    raise
                await asyncio.sleep(e.retry_after)
            except Exception as e:
                classified = classify_error(e)

                if not classified.should_retry or attempt == max_retries:
                    if classified.category == ErrorCategory.RATE_LIMITED:
                        self.health_tracker.record_rate_limit(
                            provider_name,
                            time.time() + (classified.retry_after or 60),
                        )
                    raise

                delay = classified.suggested_delay
                if classified.category == ErrorCategory.TRANSIENT:
                    delay = base_delay * 2**attempt + random.uniform(0, 0.5)
                elif classified.category == ErrorCategory.RATE_LIMITED:
                    self.health_tracker.record_rate_limit(
                        provider_name,
                        time.time() + (classified.retry_after or 60),
                    )

                logger.info(
                    "Provider '%s' error [%s], retrying in %.1fs (attempt %d/%d)",
                    provider_name,
                    classified.category.value,
                    delay,
                    attempt + 1,
                    max_retries + 1,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"Retry exhausted for provider '{provider_name}'")

    def _record_cost(self, provider_name: str, response: LLMResponse) -> None:
        """Record cost estimate from a successful response."""
        usage = response.usage or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if prompt_tokens > 0 or completion_tokens > 0:
            rec = self.cost_tracker.record(
                provider=provider_name,
                model=response.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            response.cost_estimate = rec.estimated_cost_usd

    # ── Health & cost inspection ─────────────────────────────────────────

    def get_health_summary(self) -> dict[str, Any]:
        """Return health status for all providers."""
        return {
            name: {
                "healthy": self.health_tracker.is_healthy(name),
                "consecutive_failures": self.health_tracker.get_health(name).consecutive_failures,
                "total_requests": self.health_tracker.get_health(name).total_requests,
                "total_failures": self.health_tracker.get_health(name).total_failures,
            }
            for name in self.providers
        }

    def get_cost_summary(self) -> dict[str, Any]:
        """Return cost tracking summary."""
        return self.cost_tracker.get_usage_summary()

    def _apply_caching_hints(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Apply prompt caching hints to messages for Anthropic providers.

        Marks the system message and the last two user turns with
        ``cache_control`` so Anthropic can reuse the cached prefix.
        """
        import copy
        result = copy.deepcopy(messages)
        user_indices = [i for i, m in enumerate(result) if m.role == "user"]

        for idx in user_indices[-2:]:
            msg = result[idx]
            if msg.cache_control is None:
                result[idx] = LLMMessage(
                    role=msg.role,
                    content=msg.content,
                    thinking=msg.thinking,
                    cache_control={"type": "ephemeral"},
                )

        return result
