"""Error Classifier — categorizes errors for smarter retry and recovery.

Classifies errors into categories that determine the appropriate response:
- TRANSIENT: Temporary failures that may resolve on retry (timeouts, 429, 503)
- PERMANENT: Failures that won't resolve by retrying (401, 403, bad request)
- RATE_LIMITED: Explicit rate limit responses with cooldown period
- NETWORK: Connection failures, DNS errors, unreachable hosts
- TIMEOUT: Request exceeded time limit
- UNKNOWN: Unclassified errors

Used by ProviderRouter for retry decisions and by ExecutorService for
recovery planning.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class ClassifiedError:
    category: ErrorCategory
    original_error: str
    retry_after: float | None = None
    should_retry: bool = False
    suggested_delay: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "should_retry": self.should_retry,
            "suggested_delay": self.suggested_delay,
            "retry_after": self.retry_after,
        }


_TRANSIENT_PATTERNS = [
    re.compile(r"5[0-9]{2}", re.I),
    re.compile(r"server\s+error", re.I),
    re.compile(r"service\s+unavailable", re.I),
    re.compile(r"bad\s+gateway", re.I),
    re.compile(r"gateway\s+timeout", re.I),
    re.compile(r"internal\s+server\s+error", re.I),
    re.compile(r"overloaded", re.I),
    re.compile(r"capacity", re.I),
]

_PERMANENT_PATTERNS = [
    re.compile(r"\b401\b"),
    re.compile(r"\b403\b"),
    re.compile(r"\b404\b"),
    re.compile(r"\b405\b"),
    re.compile(r"\b409\b"),
    re.compile(r"\b422\b"),
    re.compile(r"auth(entication|orization)?\s*(fail|error|invalid)", re.I),
    re.compile(r"permission\s+denied", re.I),
    re.compile(r"not\s+found", re.I),
    re.compile(r"invalid\s+api\s+key", re.I),
    re.compile(r"forbidden", re.I),
    re.compile(r"conflict", re.I),
]

_RATE_LIMIT_PATTERNS = [
    re.compile(r"\b429\b"),
    re.compile(r"rate\s*limit", re.I),
    re.compile(r"too\s+many\s+requests", re.I),
    re.compile(r"quota\s+exceeded", re.I),
    re.compile(r"throttl", re.I),
]

_NETWORK_PATTERNS = [
    re.compile(r"connection\s*(refused|reset|failed|error)", re.I),
    re.compile(r"could\s+not\s+resolve", re.I),
    re.compile(r"name\s+or\s+service\s+not\s+known", re.I),
    re.compile(r"network\s+is\s+unreachable", re.I),
    re.compile(r"no\s+route\s+to\s+host", re.I),
    re.compile(r"connect\s+timeout", re.I),
    re.compile(r"connecttimeout", re.I),
    re.compile(r"connectionerror", re.I),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"timed?\s*out", re.I),
    re.compile(r"timeout", re.I),
    re.compile(r"deadline\s+exceeded", re.I),
]


def classify_error(error: str | Exception, *, retry_after: float | None = None) -> ClassifiedError:
    """Classify an error into a category with retry guidance.

    Args:
        error: The error string or exception to classify.
        retry_after: Explicit retry-after value from HTTP headers (seconds).

    Returns:
        ClassifiedError with category and retry guidance.
    """
    if isinstance(error, Exception):
        error_str = f"{type(error).__name__}: {error}"
    else:
        error_str = str(error)

    if retry_after is not None:
        return ClassifiedError(
            category=ErrorCategory.RATE_LIMITED,
            original_error=error_str,
            retry_after=retry_after,
            should_retry=True,
            suggested_delay=retry_after,
        )

    for pattern in _RATE_LIMIT_PATTERNS:
        if pattern.search(error_str):
            return ClassifiedError(
                category=ErrorCategory.RATE_LIMITED,
                original_error=error_str,
                retry_after=60.0,
                should_retry=True,
                suggested_delay=60.0,
            )

    for pattern in _TIMEOUT_PATTERNS:
        if pattern.search(error_str):
            return ClassifiedError(
                category=ErrorCategory.TIMEOUT,
                original_error=error_str,
                should_retry=True,
                suggested_delay=2.0,
            )

    for pattern in _NETWORK_PATTERNS:
        if pattern.search(error_str):
            return ClassifiedError(
                category=ErrorCategory.NETWORK,
                original_error=error_str,
                should_retry=True,
                suggested_delay=5.0,
            )

    for pattern in _PERMANENT_PATTERNS:
        if pattern.search(error_str):
            return ClassifiedError(
                category=ErrorCategory.PERMANENT,
                original_error=error_str,
                should_retry=False,
                suggested_delay=0.0,
            )

    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(error_str):
            return ClassifiedError(
                category=ErrorCategory.TRANSIENT,
                original_error=error_str,
                should_retry=True,
                suggested_delay=3.0,
            )

    return ClassifiedError(
        category=ErrorCategory.UNKNOWN,
        original_error=error_str,
        should_retry=False,
        suggested_delay=0.0,
    )
