"""Audit hash chain — tamper-evident append-only ledger (spec G4/P4).

Each audit event's entry_hash is:

    SHA-256( prev_entry_hash || id || created_at || event_type ||
             actor || task_id || step_id || canonical_json(detail) )

The chain is global (single SQLite writer at a time, so sequencing is
safe). Rows written before the chain existed have NULL hashes; the
verifier anchors at the first hashed row and ignores NULLs before it —
but any NULL *after* the chain head is a tamper signal.

`canonical_json` sorts dict keys at every level so DB JSON re-encoding
cannot change the digest.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64  # prev of the first hashed row


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding (sorted keys, no whitespace)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def canonical_ts(value: Any) -> str:
    """Normalize timestamps for hashing.

    SQLite round-trips tz-aware datetimes as naive; both forms must hash
    identically, so naive values are treated as UTC and everything is
    rendered as a UTC ISO-8601 string.
    """
    from datetime import datetime, timezone

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def compute_entry_hash(
    *,
    prev_entry_hash: str | None,
    event_id: str,
    created_at: Any,
    event_type: str,
    actor: str,
    task_id: str | None,
    step_id: str | None,
    detail: dict[str, Any] | None,
) -> str:
    parts = [
        (prev_entry_hash or GENESIS),
        event_id,
        canonical_ts(created_at),
        str(event_type),
        str(actor),
        str(task_id or ""),
        str(step_id or ""),
        canonical_json(detail),
    ]
    payload = "\x1f".join(parts)  # unit separator — cannot appear in JSON output
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
