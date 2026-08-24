"""Shared argument sanitization for operator-facing API responses.

Used by task-detail and gateway-approval views so approvers can inspect
*what* a step will do without ever receiving credential material
(passwords, tokens, API keys, secret references).  Fail-closed: keys that
merely *contain* a sensitive token are redacted too, and redaction is
applied recursively through nested dicts and lists.

This module is display-only.  It never feeds execution paths — the
executor consumes raw ``TaskStep.args`` internally.
"""

from __future__ import annotations

from typing import Any

REDACTED = "***REDACTED***"

# Unambiguous substrings: any key containing one of these is redacted.
_SENSITIVE_SUBSTRINGS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "credential",
    "signature",
    "cert_password",
)

# Exact matches only — kept separate so short stems like "auth" do not
# redact unrelated keys such as "author".
_SENSITIVE_EXACT = frozenset({
    "auth",
    "authorization",
})


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SENSITIVE_EXACT:
        return True
    return any(token in lowered for token in _SENSITIVE_SUBSTRINGS)


def sanitize_args(value: Any) -> Any:
    """Return a redacted deep copy of ``value`` (dict / list / scalar).

    Sensitive keys are replaced with :data:`REDACTED` regardless of the
    value they hold (a ``SecretRef`` mapping under a key like
    ``secret``/``secret_ref`` is therefore redacted whole — its plaintext
    never reaches the response).
    """
    if isinstance(value, dict):
        return {
            k: REDACTED if _is_sensitive_key(str(k)) else sanitize_args(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize_args(v) for v in value]
    return value
