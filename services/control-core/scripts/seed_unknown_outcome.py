#!/usr/bin/env python3
"""Seed one UNKNOWN_OUTCOME effect into a *throwaway* test database.

Release-gate fixture (GA-1.2): used to exercise the desktop
unknown-outcome queue (GET /api/v1/effects/unknown-outcomes, reconcile,
409-on-terminal) against an isolated, one-off test data directory.

Safety: this tool REFUSES to touch the real per-user data directory
(``%LOCALAPPDATA%\\zcode``).  Point ``--db-path`` at a disposable file
(e.g. ``%TEMP%\\ga-fixture\\agent_platform.db``).

Usage:
    python scripts/seed_unknown_outcome.py --db-path "C:\\Temp\\ga-fixture\\agent_platform.db"
    python scripts/seed_unknown_outcome.py --db-path ... --tool-name file.delete
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.db.models import (
    Base,
    CapabilityGrantModel,
    EffectClassDB,
    EffectStatusDB,
    LeaseModel,
)
from packages.db.repositories.effect_repo import EffectRepository
from packages.db.session import Base as AppBase


def _real_user_data_dir() -> Path | None:
    """Return the real per-user zcode data dir (%LOCALAPPDATA%\\zcode), if known."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return (Path(local_app_data) / "zcode").resolve()


def ensure_not_real_data_dir(db_path: Path) -> None:
    """Refuse to operate on the real %LOCALAPPDATA%\\zcode directory."""
    real_dir = _real_user_data_dir()
    if real_dir is None:
        return
    resolved = db_path.resolve()
    try:
        resolved.relative_to(real_dir)
    except ValueError:
        return  # outside the real data dir — OK
    raise SystemExit(
        f"REFUSED: {resolved} is inside the real user data directory "
        f"{real_dir}. This fixture tool may only write to a disposable "
        "test database path."
    )


def seed(db_path: Path, tenant_id: str, tool_name: str) -> dict:
    ensure_not_real_data_dir(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)

    step_run_id = f"fixture-step-{uuid.uuid4()}"
    now = datetime.now(UTC)

    with Session(engine) as db:
        grant = CapabilityGrantModel(
            tenant_id=tenant_id, step_run_id=step_run_id,
            handle_digest="h" * 64, nonce="n" * 16,
            bound_args_hash="a" * 64, risk_level="high",
            resource_scope={}, security_context_digest="sc" * 32,
            status="issued", issued_at=now,
            expires_at=now + timedelta(hours=1), max_uses=1,
        )
        lease = LeaseModel(
            tenant_id=tenant_id, worker_id="fixture-worker",
            step_run_id=step_run_id, fencing_token=1,
            status="active", expires_at=now + timedelta(hours=1),
        )
        db.add_all([grant, lease])
        db.flush()

        effect = EffectRepository.create(
            db,
            tenant_id=tenant_id, step_run_id=step_run_id,
            grant_id=grant.id, lease_id=lease.id,
            fencing_token=1, status=EffectStatusDB.UNKNOWN_OUTCOME,
            effect_class=EffectClassDB.NON_RETRYABLE, tool_name=tool_name,
            security_context_digest="sc" * 32, created_at=now,
        )
        db.commit()
        return {
            "db_path": str(db_path),
            "tenant_id": tenant_id,
            "effect_id": effect.id,
            "step_run_id": step_run_id,
            "status": EffectStatusDB.UNKNOWN_OUTCOME.value,
            "tool_name": tool_name,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed one UNKNOWN_OUTCOME effect into a disposable test DB."
    )
    parser.add_argument(
        "--db-path", required=True,
        help="Absolute path to a disposable SQLite DB (never %LOCALAPPDATA%\\zcode).",
    )
    parser.add_argument("--tenant-id", default="ga-fixture")
    parser.add_argument("--tool-name", default="file.delete")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.is_absolute():
        raise SystemExit("REFUSED: --db-path must be absolute.")

    result = seed(db_path, args.tenant_id, args.tool_name)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
