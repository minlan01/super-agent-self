"""Messaging router — loads config, instantiates providers, and routes message requests.

Supports:
- Direct dispatch: router.send(message, provider="telegram")
- Failover dispatch: router.send(message, chain="default")
- Webhook handling: router.handle_webhook(platform, headers, body)
- Health tracking via ProviderHealthTracker (imported from llm_gateway)
- Credential pooling via CredentialPool (imported from llm_gateway)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import yaml

from packages.llm_gateway.credential_pool import CredentialPool
from packages.llm_gateway.health_tracker import ProviderHealthTracker
from packages.messaging_gateway.base import (
    BaseMessagingProvider,
    InboundMessage,
    MessageDeliveryStatus,
    OutboundMessage,
)
from packages.messaging_gateway.discord_provider import DiscordProvider
from packages.messaging_gateway.feishu_provider import FeishuProvider
from packages.messaging_gateway.slack_provider import SlackProvider
from packages.messaging_gateway.telegram_provider import TelegramProvider

logger = logging.getLogger(__name__)

_PROVIDER_TYPES: dict[str, type[BaseMessagingProvider]] = {
    "telegram": TelegramProvider,
    "discord": DiscordProvider,
    "slack": SlackProvider,
    "feishu": FeishuProvider,
}

_MAX_SEND_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0


class MessagingRouter:
    """Routes messaging requests to the appropriate platform provider.

    Supports both direct dispatch and failover chains.
    """

    def __init__(self, config_path: str = "configs/messaging.yaml") -> None:
        self.config_path = config_path
        self.providers: dict[str, BaseMessagingProvider] = {}
        self.default_provider: str = "telegram"
        self.credential_pools: dict[str, CredentialPool] = {}
        self.health_tracker = ProviderHealthTracker()
        self.failover_chains: dict[str, list[str]] = {}
        self._load_config()

    def _load_config(self) -> None:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("Messaging config not found at '%s', using defaults", self.config_path)
            cfg = {}

        providers_cfg = cfg.get("providers", {})
        defaults = cfg.get("defaults", {})
        failover_cfg = cfg.get("failover", {})

        # Default provider
        env_provider = os.environ.get("MESSAGING_PROVIDER")
        self.default_provider = env_provider or defaults.get("provider", "telegram")

        # Instantiate each configured provider
        for name, prov_cfg in providers_cfg.items():
            if not prov_cfg.get("enabled", True):
                continue

            provider_type = prov_cfg.get("type")
            cls = _PROVIDER_TYPES.get(provider_type)
            if cls is None:
                logger.warning("Unknown messaging provider type '%s' for '%s'", provider_type, name)
                continue

            config = {**prov_cfg, "name": name}
            try:
                self.providers[name] = cls(config)
                logger.info("Initialized messaging provider '%s' (%s)", name, provider_type)
            except Exception:
                logger.exception("Failed to initialize messaging provider '%s'", name)

            # Set up credential pool
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

        # Auto-generate default chain
        if "default" not in self.failover_chains:
            available = list(self.providers.keys())
            if available:
                self.failover_chains["default"] = available[:3]

        # Ensure default provider exists
        if self.default_provider not in self.providers and self.providers:
            self.default_provider = next(iter(self.providers))
            logger.info("Default messaging provider set to '%s'", self.default_provider)

    def get_provider(self, name: str | None = None) -> BaseMessagingProvider:
        """Get a provider by name, or return default."""
        key = name or self.default_provider
        if key not in self.providers:
            raise ValueError(
                f"Messaging provider '{key}' not found. Available: {list(self.providers)}"
            )
        return self.providers[key]

    async def send(
        self,
        message: OutboundMessage,
        provider: str | None = None,
        chain: str | None = None,
    ) -> MessageDeliveryStatus:
        """Send a message using the specified provider or failover chain."""
        if chain is not None:
            return await self.send_with_failover(message, chain=chain)

        p = self.get_provider(provider or message.platform or None)
        last_error = ""
        for attempt in range(_MAX_SEND_RETRIES):
            try:
                result = await p.send(message)
                if result.status == "sent":
                    self.health_tracker.record_success(p.name)
                    return result
                last_error = result.error or "delivery failed"
                self.health_tracker.record_failure(p.name, last_error)
            except Exception as e:
                last_error = str(e)
                self.health_tracker.record_failure(p.name, last_error)

            if attempt < _MAX_SEND_RETRIES - 1:
                delay = _RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.info(
                    "Messaging provider '%s' attempt %d/%d failed: %s — retrying in %.1fs",
                    p.name, attempt + 1, _MAX_SEND_RETRIES, last_error[:80], delay,
                )
                await asyncio.sleep(delay)

        return MessageDeliveryStatus(
            message_id="", platform=p.name, status="failed",
            error=f"Failed after {_MAX_SEND_RETRIES} attempts. Last error: {last_error}",
        )

    async def send_with_failover(
        self,
        message: OutboundMessage,
        chain: str = "default",
    ) -> MessageDeliveryStatus:
        """Try providers in failover chain order, skipping unhealthy ones."""
        providers = self.failover_chains.get(chain) or [self.default_provider]
        last_error = ""

        # Separate healthy and unhealthy
        healthy = [p for p in providers if self.health_tracker.is_healthy(p)]
        unhealthy = [p for p in providers if not self.health_tracker.is_healthy(p)]
        ordered = healthy + unhealthy

        for name in ordered:
            if name not in self.providers:
                continue
            try:
                result = await self.providers[name].send(message)
                if result.status == "sent":
                    self.health_tracker.record_success(name)
                    return result
                # Delivery failed but no exception
                self.health_tracker.record_failure(name, result.error or "delivery failed")
                last_error = result.error or "delivery failed"
            except Exception as e:
                self.health_tracker.record_failure(name, str(e))
                last_error = str(e)
                logger.warning(
                    "Messaging provider '%s' failed: %s — trying next",
                    name, last_error[:80],
                )

        return MessageDeliveryStatus(
            message_id="",
            platform="",
            status="failed",
            error=f"All providers in chain '{chain}' failed. Last error: {last_error}",
        )

    async def handle_webhook(
        self, platform: str, headers: dict[str, str], body: bytes
    ) -> InboundMessage | None:
        """Validate and parse an inbound webhook from a platform."""
        if platform not in self.providers:
            logger.warning("Webhook from unknown platform: '%s'", platform)
            return None

        provider = self.providers[platform]
        try:
            return await provider.validate_webhook(headers, body)
        except Exception:
            logger.exception("Webhook validation error for '%s'", platform)
            return None

    def get_health_summary(self) -> dict[str, Any]:
        """Return health status for all messaging providers."""
        return {
            name: {
                "healthy": self.health_tracker.is_healthy(name),
                **self.health_tracker.get_health(name).__dict__,
            }
            for name in self.providers
        }
