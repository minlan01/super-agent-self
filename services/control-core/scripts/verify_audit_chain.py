#!/usr/bin/env python3
"""Verify the audit hash chain (spec: tamper-evidence, 100% pass for GA).

Exit 0 = chain intact; exit 1 = tamper detected (fails closed).

Usage:
    python scripts/verify_audit_chain.py            # uses default DB
    DATABASE_URL=sqlite:///path.db python scripts/verify_audit_chain.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from packages.db.audit_chain import compute_entry_hash  # noqa: E402
from packages.db.models import AuditEvent  # noqa: E402
from packages.db.session import SessionLocal  # noqa: E402


def verify() -> int:
    db = SessionLocal()
    try:
        rows = list(db.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)
        ))
    finally:
        db.close()

    hashed = [r for r in rows if r.entry_hash]
    pre_chain = [r for r in rows if not r.entry_hash]

    # Rows after the chain head must not be unhashed (deleted-or-zeroed hash).
    first_hash_idx = rows.index(hashed[0]) if hashed else len(rows)
    trailing_unhashed = [r for r in rows[first_hash_idx:] if not r.entry_hash]
    if trailing_unhashed:
        print(f"TAMPER: {len(trailing_unhashed)} unhashed row(s) after chain head")
        return 1

    if not hashed:
        print(f"chain empty ({len(pre_chain)} pre-chain rows) — nothing to verify")
        return 0

    print(f"chain: {len(hashed)} hashed rows (+{len(pre_chain)} pre-chain ignored)")

    prev = None
    for row in hashed:
        expected = compute_entry_hash(
            prev_entry_hash=row.prev_entry_hash,
            event_id=row.id,
            created_at=row.created_at,
            event_type=str(getattr(row.event_type, "value", row.event_type)),
            actor=str(row.actor),
            task_id=row.task_id,
            step_id=row.step_id,
            detail=row.detail,
        )
        if expected != row.entry_hash:
            print(f"TAMPER: row {row.id} hash mismatch "
                  f"(stored={row.entry_hash[:12]}… computed={expected[:12]}…)")
            return 1
        if prev is not None and row.prev_entry_hash != prev:
            print(f"TAMPER: row {row.id} breaks the chain "
                  f"(prev stored={row.prev_entry_hash[:12]}… expected={prev[:12]}…)")
            return 1
        prev = row.entry_hash

    print(f"OK: audit chain intact, head={prev[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(verify())
