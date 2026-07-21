"""Provider Health Tracker — monitors LLM provider health for failover decisions."""

from __future__ import annotations

import logging
import threading
import time

from packages.llm_gateway.base import ProviderHealth

logger = logging.getLogger(__name__)


class ProviderHealthTracker:
    """In-memory health tracker for LLM providers.

    Tracks consecutive failures, rate-limit cooldowns, and overall
    request/failure counts. Used by ProviderRouter to skip unhealthy
    providers during failover.
    """

    def __init__(self) -> None:
        self._health: dict[str, ProviderHealth] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, provider_name: str) -> ProviderHealth:
        if provider_name not in self._health:
            self._health[provider_name] = ProviderHealth(provider_name=provider_name)
        return self._health[provider_name]

    def record_success(self, provider_name: str) -> None:
        """Record a successful request — resets consecutive failure count."""
        with self._lock:
            h = self._get_or_create(provider_name)
            h.consecutive_failures = 0
            h.total_requests += 1
            h.rate_limit_reset_at = None
            h.circuit_open_until = None

    def record_failure(self, provider_name: str, reason: str) -> None:
        """Record a failed request — increments consecutive failure count."""
        with self._lock:
            h = self._get_or_create(provider_name)
            h.consecutive_failures += 1
            h.last_failure_time = time.time()
            h.last_failure_reason = reason
            h.total_requests += 1
            h.total_failures += 1
            if h.consecutive_failures >= h.max_consecutive_failures:
                h.circuit_open_until = time.time() + h.circuit_cooldown_seconds
        logger.warning(
            "Provider '%s' failure #%d: %s",
            provider_name, h.consecutive_failures, reason[:80],
        )

    def record_rate_limit(self, provider_name: str, reset_at: float) -> None:
        """Record a rate-limit event — provider is unhealthy until reset_at."""
        with self._lock:
            h = self._get_or_create(provider_name)
            h.rate_limit_reset_at = reset_at
        logger.info(
            "Provider '%s' rate-limited until %.0f (in %.0fs)",
            provider_name, reset_at, max(0, reset_at - time.time()),
        )

    def is_healthy(self, provider_name: str) -> bool:
        """Check if a provider is currently healthy."""
        with self._lock:
            h = self._get_or_create(provider_name)
            return h.is_healthy()

    def get_health(self, provider_name: str) -> ProviderHealth:
        """Get the health record for a provider."""
        with self._lock:
            return self._get_or_create(provider_name)

    def get_all_health(self) -> dict[str, ProviderHealth]:
        """Return health records for all known providers."""
        with self._lock:
            return dict(self._health)

    def reset(self, provider_name: str) -> None:
        """Manually reset a provider's health (e.g., after operator intervention)."""
        with self._lock:
            if provider_name in self._health:
                self._health[provider_name] = ProviderHealth(provider_name=provider_name)
                logger.info("Reset health for provider '%s'", provider_name)
