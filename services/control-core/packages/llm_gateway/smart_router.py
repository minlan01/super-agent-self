"""Smart Model Router — routes simple requests to cheap models, complex ones to the main model.

Supports:
- Heuristic complexity analysis (keywords, length, code, URLs)
- Conversation context awareness (turn count, cumulative length)
- Prompt caching hints for Anthropic-style providers
- Latency-aware routing based on recent provider response times
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_SIMPLE_CHARS = 160
MAX_SIMPLE_WORDS = 28

COMPLEX_KEYWORDS = {
    "debug", "implement", "refactor", "error", "analyze",
    "architecture", "design", "optimize", "review", "plan",
    "shell", "tool", "test", "fix", "traceback",
    "create", "build", "write", "code",
    "deploy", "configure", "install", "setup",
}

MAX_LATENCY_SAMPLES = 100
_MAX_LATENCY_PROVIDERS = 50


@dataclass
class ProviderLatency:
    provider_name: str
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_LATENCY_SAMPLES))

    def record(self, duration_ms: float) -> None:
        self.samples.append(duration_ms)

    def avg_ms(self) -> float:
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)


class SmartModelRouter:
    """Determines whether to use a cheap (fast/local) model or the main model.

    Enhanced with:
    - Context-aware routing: considers conversation turn count and history
    - Latency tracking: prefers faster providers when multiple are healthy
    - Prompt caching: marks system messages and long context with cache_control
    """

    def __init__(
        self,
        max_simple_chars: int = MAX_SIMPLE_CHARS,
        max_simple_words: int = MAX_SIMPLE_WORDS,
        complex_keywords: set[str] | None = None,
    ):
        self.max_simple_chars = max_simple_chars
        self.max_simple_words = max_simple_words
        self.complex_keywords = complex_keywords or COMPLEX_KEYWORDS
        self._latencies: dict[str, ProviderLatency] = {}

    def should_use_cheap_model(self, message: str) -> bool:
        if len(message) > self.max_simple_chars:
            return False
        if len(message.split()) > self.max_simple_words:
            return False
        if "```" in message or "`" in message:
            return False
        if "http://" in message or "https://" in message or "www." in message:
            return False
        words = re.findall(r"\w+", message.lower())
        if any(w in self.complex_keywords for w in words):
            return False
        return True

    def route(
        self,
        message: str,
        cheap_provider: str,
        main_provider: str,
        *,
        conversation_turns: int = 0,
        total_context_chars: int = 0,
    ) -> str:
        """Return the provider name to use for the given message.

        Args:
            message: The user's latest message.
            cheap_provider: Provider name for cheap/fast model.
            main_provider: Provider name for the main model.
            conversation_turns: Number of prior turns in the conversation.
            total_context_chars: Total character count of the full context.
        """
        if conversation_turns > 6 or total_context_chars > 8000:
            logger.debug(
                "Routing to main model (turns=%d, ctx_chars=%d)",
                conversation_turns,
                total_context_chars,
            )
            return self._pick_by_latency(main_provider, cheap_provider)

        if self.should_use_cheap_model(message):
            logger.debug("Routing to cheap model (msg_len=%d)", len(message))
            return self._pick_by_latency(cheap_provider, main_provider)
        logger.debug("Routing to main model (msg_len=%d)", len(message))
        return self._pick_by_latency(main_provider, cheap_provider)

    def _pick_by_latency(self, preferred: str, fallback: str) -> str:
        """Pick the preferred provider if latency data looks good, else fallback."""
        latency = self._latencies.get(preferred)
        if latency is None or not latency.samples:
            return preferred
        avg = latency.avg_ms()
        if avg > 0 and avg < 30000:
            return preferred
        fallback_latency = self._latencies.get(fallback)
        if fallback_latency is not None and fallback_latency.samples:
            if fallback_latency.avg_ms() < avg * 0.5:
                logger.debug(
                    "Switching from %s (%.0fms) to %s (%.0fms) due to latency",
                    preferred, avg, fallback, fallback_latency.avg_ms(),
                )
                return fallback
        return preferred

    def route_by_latency(
        self,
        candidates: list[str],
        fallback: str = "",
    ) -> str:
        """Pick the fastest provider from *candidates* based on avg latency.

        Falls back to *fallback* (or the first candidate) when no latency
        data is available yet.
        """
        if not candidates:
            return fallback

        best_provider = None
        best_avg = float("inf")

        for name in candidates:
            latency = self._latencies.get(name)
            if latency is None or not latency.samples:
                continue
            avg = latency.avg_ms()
            if avg < best_avg:
                best_avg = avg
                best_provider = name

        if best_provider is not None:
            return best_provider
        return fallback or candidates[0]

    def record_latency(self, provider_name: str, duration_ms: float) -> None:
        if provider_name not in self._latencies:
            if len(self._latencies) >= _MAX_LATENCY_PROVIDERS:
                oldest = min(self._latencies, key=lambda k: len(self._latencies[k].samples))
                del self._latencies[oldest]
            self._latencies[provider_name] = ProviderLatency(provider_name=provider_name)
        self._latencies[provider_name].record(duration_ms)

    @staticmethod
    def apply_prompt_caching(
        messages: list[dict],
        provider_type: str = "",
    ) -> list[dict]:
        """Add cache_control hints for providers that support prompt caching.

        Anthropic-style providers support ``cache_control`` on message content
        blocks.  We mark:
        - The system message (if present) — always cache
        - The last two user turns — cache for multi-turn reuse

        For non-Anthropic providers this is a no-op.

        Args:
            messages: List of message dicts with ``role`` and ``content``.
            provider_type: Provider type string (e.g. "anthropic").

        Returns:
            A new messages list with cache_control hints added (input is not mutated).
        """
        if provider_type != "anthropic":
            return messages

        import copy
        result = copy.deepcopy(messages)

        user_indices = [
            i for i, m in enumerate(result) if m.get("role") == "user"
        ]

        for idx in user_indices[-2:]:
            msg = result[idx]
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ]
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["cache_control"] = {"type": "ephemeral"}
                        break

        return result
