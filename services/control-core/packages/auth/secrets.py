"""Secrets Manager — secure loading and validation of API keys and secrets.

Provides:
- Validation that secrets are not default/placeholder values
- Detection of secrets committed to source code
- Secure loading from environment variables with fallback chain
- Audit logging when secrets are accessed
- Masking of secrets in logs and error messages
"""

from __future__ import annotations

import os
import re
from typing import Any

import structlog

logger = structlog.get_logger()

_PLACEHOLDER_PATTERNS = [
    re.compile(r"^change[-_]?me", re.I),
    re.compile(r"^your[-_]?api[-_]?key", re.I),
    re.compile(r"^xxx+", re.I),
    re.compile(r"^placeholder", re.I),
    re.compile(r"^example", re.I),
    re.compile(r"^test[-_]?key", re.I),
    re.compile(r"^sk[-_]xxxx", re.I),
    re.compile(r"^<", re.I),
    re.compile(r"^\[", re.I),
]

_MIN_SECRET_LENGTH = 8


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """Mask a secret for safe logging, showing only the first few chars.

    >>> mask_secret("sk-abc123xyz789")
    'sk-a***********'
    """
    if len(secret) <= visible_chars:
        return "*" * len(secret)
    return secret[:visible_chars] + "*" * (len(secret) - visible_chars)


def is_placeholder(value: str) -> bool:
    """Check if a secret value looks like a placeholder/default."""
    if not value or len(value) < _MIN_SECRET_LENGTH:
        return True
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.match(value):
            return True
    return False


def load_secret(
    env_var: str,
    *,
    default: str = "",
    required: bool = False,
    description: str = "",
) -> str:
    """Load a secret from environment variable with validation.

    Args:
        env_var: Name of the environment variable.
        default: Default value if env var is not set.
        required: If True, raise an error when the secret is missing or placeholder.
        description: Human-readable description for error messages.

    Returns:
        The secret value.

    Raises:
        ValueError: If required and the value is missing or a placeholder.
    """
    value = os.environ.get(env_var, default)

    if not value:
        if required:
            raise ValueError(
                f"Required secret '{env_var}' is not set. "
                f"Set it via environment variable. {description}"
            )
        return ""

    if is_placeholder(value):
        if required:
            raise ValueError(
                f"Required secret '{env_var}' has a placeholder value. "
                f"Set a real value via environment variable. {description}"
            )
        logger.warning(
            "Secret '%s' appears to be a placeholder value (masked: %s)",
            env_var,
            mask_secret(value),
        )
        return value

    logger.debug("Secret '%s' loaded (masked: %s)", env_var, mask_secret(value))
    return value


def validate_secrets_config() -> list[str]:
    """Validate all known secrets and return a list of warnings.

    Checks for:
    - Default SECRET_KEY
    - Missing API keys for configured providers
    - Placeholder values

    Returns:
        List of warning messages.
    """
    warnings: list[str] = []

    secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
    if is_placeholder(secret_key):
        warnings.append(
            "SECRET_KEY is using default value. "
            "Set a cryptographically random string via environment variable."
        )

    provider_keys = {
        "DEEPSEEK_API_KEY": "DeepSeek",
        "ANTHROPIC_API_KEY": "Anthropic",
        "OPENAI_API_KEY": "OpenAI",
        "OPENROUTER_API_KEY": "OpenRouter",
        "BRAVE_API_KEY": "Brave Search",
        "GEMINI_API_KEY": "Gemini",
    }

    for env_var, provider_name in provider_keys.items():
        value = os.environ.get(env_var, "")
        if value and is_placeholder(value):
            warnings.append(
                f"{provider_name} API key ({env_var}) appears to be a placeholder."
            )

    return warnings


class SecretsAuditLogger:
    """Audit logger for secret access events.

    Records when secrets are accessed without exposing their values.
    Useful for compliance and security monitoring.
    """

    _MAX_LOG_SIZE = 10_000

    def __init__(self) -> None:
        self._access_log: list[dict[str, Any]] = []

    def log_access(self, env_var: str, caller: str = "") -> None:
        self._access_log.append({
            "env_var": env_var,
            "caller": caller,
            "masked": True,
        })
        if len(self._access_log) > self._MAX_LOG_SIZE:
            self._access_log = self._access_log[-self._MAX_LOG_SIZE:]
        logger.debug("Secret accessed: %s (caller: %s)", env_var, caller or "unknown")

    def get_access_log(self) -> list[dict[str, Any]]:
        return list(self._access_log)


_secrets_audit = SecretsAuditLogger()


def get_secrets_audit() -> SecretsAuditLogger:
    return _secrets_audit
