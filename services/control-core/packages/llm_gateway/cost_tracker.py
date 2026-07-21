"""Cost Tracker — estimates and records LLM API usage costs."""

from __future__ import annotations

import structlog
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from packages.llm_gateway.base import CostRecord

logger = structlog.get_logger()

# Built-in cost estimates per 1K tokens (USD).
# Format: {provider_name: {model_pattern: (input_per_1k, output_per_1k)}}
_BUILTIN_COSTS: dict[str, dict[str, tuple[float, float]]] = {
    "deepseek": {
        "deepseek-chat": (0.00014, 0.00028),
        "deepseek-reasoner": (0.00055, 0.00219),
    },
    "anthropic": {
        "claude-sonnet": (0.003, 0.015),
        "claude-opus": (0.015, 0.075),
        "claude-haiku": (0.00025, 0.00125),
    },
    "openrouter": {
        "default": (0.003, 0.015),
    },
    "openai": {
        "gpt-4o": (0.0025, 0.01),
        "gpt-4o-mini": (0.00015, 0.0006),
    },
    "gemini": {
        "gemini-2.0-flash": (0.00025, 0.0005),
        "gemini-2.5-pro": (0.00125, 0.005),
    },
    "ollama": {
        "default": (0.0, 0.0),
    },
    "llamacpp": {
        "default": (0.0, 0.0),
    },
    "mock": {
        "default": (0.0, 0.0),
    },
}

MAX_RECORDS = 10_000


class BudgetExceededError(Exception):
    """Raised when daily LLM cost budget is exceeded."""
    pass


class CostTracker:
    """Tracks per-request cost estimates with bounded history.

    Persists records to DB when a session is provided via flush_to_db().
    Suitable for both real-time in-memory lookups and historical DB queries.
    Supports optional daily budget enforcement.
    """

    def __init__(
        self,
        max_records: int = MAX_RECORDS,
        daily_budget_usd: float | None = None,
    ) -> None:
        self._records: deque[CostRecord] = deque(maxlen=max_records)
        self._custom_costs: dict[str, dict[str, tuple[float, float]]] = {}
        self._flushed_count: int = 0
        self._daily_budget_usd = daily_budget_usd
        self._lock = threading.Lock()

    def set_custom_costs(self, provider: str, model: str, input_per_1k: float, output_per_1k: float) -> None:
        """Override cost estimates for a specific provider+model."""
        if provider not in self._custom_costs:
            self._custom_costs[provider] = {}
        self._custom_costs[provider][model] = (input_per_1k, output_per_1k)

    def estimate_cost(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate the cost of a request based on token usage."""
        input_cost, output_cost = self._get_rate(provider, model)
        cost = (prompt_tokens / 1000.0) * input_cost + (completion_tokens / 1000.0) * output_cost
        return round(cost, 6)

    def record(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> CostRecord:
        """Record a cost entry and return the CostRecord.

        Raises BudgetExceededError if daily budget is set and exceeded.
        Thread-safe: uses a lock to prevent budget bypass under concurrency.
        """
        with self._lock:
            cost = self.estimate_cost(provider, model, prompt_tokens, completion_tokens)
            rec = CostRecord(
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=cost,
            )
            self._records.append(rec)

            try:
                from packages.middleware.prometheus import registry
                registry.llm_cost_total.inc(
                    value=rec.estimated_cost_usd,
                    labels={"provider": rec.provider, "model": rec.model},
                )
            except Exception:
                logger.debug("Prometheus cost metric recording failed", exc_info=True)

            if self._daily_budget_usd is not None:
                now = datetime.now(UTC)
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_cost = self.get_total_cost(since=start_of_day.timestamp())
                if today_cost > self._daily_budget_usd:
                    logger.warning(
                        "Daily budget exceeded: $%.4f / $%.2f",
                        today_cost,
                        self._daily_budget_usd,
                    )
                    raise BudgetExceededError(
                        f"Daily budget exceeded: ${today_cost:.4f} / ${self._daily_budget_usd:.2f}"
                    )

            return rec

    def get_total_cost(self, provider: str | None = None, since: float | None = None) -> float:
        """Get total estimated cost, optionally filtered by provider and/or time."""
        total = 0.0
        for r in self._records:
            if provider is not None and r.provider != provider:
                continue
            if since is not None and r.timestamp < since:
                continue
            total += r.estimated_cost_usd
        return round(total, 6)

    def get_usage_summary(self, since: float | None = None) -> dict[str, Any]:
        """Get usage breakdown by provider and model."""
        summary: dict[str, dict[str, Any]] = {}
        for r in self._records:
            if since is not None and r.timestamp < since:
                continue
            key = f"{r.provider}/{r.model}"
            if key not in summary:
                summary[key] = {
                    "provider": r.provider,
                    "model": r.model,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "requests": 0,
                    "estimated_cost_usd": 0.0,
                }
            s = summary[key]
            s["prompt_tokens"] += r.prompt_tokens
            s["completion_tokens"] += r.completion_tokens
            s["requests"] += 1
            s["estimated_cost_usd"] += r.estimated_cost_usd

        # Round costs
        for s in summary.values():
            s["estimated_cost_usd"] = round(s["estimated_cost_usd"], 6)

        return {"total_cost_usd": self.get_total_cost(since=since), "breakdown": list(summary.values())}

    def flush_to_db(self, db: Any) -> int:
        """Persist unflushed in-memory records to the llm_cost_records table.

        Args:
            db: SQLAlchemy Session instance.

        Returns:
            Number of records flushed.
        """
        from packages.db.models import LLMCostRecord as CostRecordModel

        unflushed = list(self._records)[self._flushed_count:]
        if not unflushed:
            return 0

        now = datetime.now(UTC)
        records = [
            CostRecordModel(
                id=str(uuid.uuid4()),
                provider=rec.provider,
                model=rec.model,
                prompt_tokens=rec.prompt_tokens,
                completion_tokens=rec.completion_tokens,
                estimated_cost_usd=rec.estimated_cost_usd,
                created_at=now,
                updated_at=now,
            )
            for rec in unflushed
        ]
        db.add_all(records)
        db.flush()
        self._flushed_count = len(self._records)
        logger.info("Flushed %d cost records to DB", len(unflushed))
        return len(unflushed)

    def _get_rate(self, provider: str, model: str) -> tuple[float, float]:
        """Look up cost rate (input_per_1k, output_per_1k) for provider+model."""
        # Custom overrides first
        if provider in self._custom_costs:
            costs = self._custom_costs[provider]
            if model in costs:
                return costs[model]
            if "default" in costs:
                return costs["default"]

        # Built-in costs — try exact match then prefix match then default
        if provider in _BUILTIN_COSTS:
            costs = _BUILTIN_COSTS[provider]
            if model in costs:
                return costs[model]
            # Prefix match (e.g., "claude-sonnet-4-20250514" matches "claude-sonnet")
            for pattern, rates in costs.items():
                if pattern != "default" and model.startswith(pattern):
                    return rates
            if "default" in costs:
                return costs["default"]

        # Unknown provider — return zero
        return (0.0, 0.0)
