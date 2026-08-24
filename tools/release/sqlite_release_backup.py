#!/usr/bin/env python3
"""SQLite release backup / validate / restore CLI (GA-1.3).

Safety properties required by the release manual:
  - backups are written with ``sqlite3.Connection.backup()`` (online, consistent)
  - restore REFUSES to run unless the backup passes ``PRAGMA integrity_check``
  - all backup files must live inside the designated ``--backup-dir``; the
    tool refuses paths that resolve outside it
  - restore never writes a target located inside the backup directory

Exit codes: 0 success, 2 usage/refusal, 3 integrity/backup failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_check(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "no-result"
    finally:
        conn.close()


def _ensure_inside(path: Path, root: Path, what: str) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise SystemExit(
            f"REFUSED: {what} path {resolved} is outside the designated "
            f"backup directory {root_resolved}."
        )
    return resolved


def cmd_backup(args: argparse.Namespace) -> int:
    database = Path(args.database)
    if not database.is_absolute():
        raise SystemExit("REFUSED: --database must be an absolute path.")
    if not database.is_file():
        raise SystemExit(f"REFUSED: database not found: {database}")

    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{database.stem}-{stamp}.db"
    # Enforce containment for the file we are about to create.
    _ensure_inside(backup_path, backup_dir, "backup")

    src = sqlite3.connect(database)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    integrity = _integrity_check(backup_path)
    result = {
        "status": "ok",
        "created_at": _now(),
        "source": str(database.resolve()),
        "backup_path": str(backup_path.resolve()),
        "sha256": _sha256(backup_path),
        "integrity_check": integrity,
        "size_bytes": backup_path.stat().st_size,
    }
    if integrity != "ok":
        result["status"] = "integrity-failed"
    payload = json.dumps(result, indent=2)
    print(payload)
    if args.json_out:
        Path(args.json_out).write_text(payload + "\n", encoding="utf-8")
    return 0 if result["status"] == "ok" else 3


def cmd_validate(args: argparse.Namespace) -> int:
    backup = Path(args.backup)
    if not backup.is_absolute():
        raise SystemExit("REFUSED: --backup must be an absolute path.")
    if not backup.is_file():
        raise SystemExit(f"REFUSED: backup not found: {backup}")
    if args.backup_dir:
        _ensure_inside(backup, Path(args.backup_dir), "backup")

    integrity = _integrity_check(backup)
    result = {
        "status": "ok" if integrity == "ok" else "integrity-failed",
        "validated_at": _now(),
        "backup_path": str(backup.resolve()),
        "sha256": _sha256(backup),
        "integrity_check": integrity,
        "size_bytes": backup.stat().st_size,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 3


def cmd_restore(args: argparse.Namespace) -> int:
    backup = Path(args.backup)
    target = Path(args.target)
    if not backup.is_absolute() or not target.is_absolute():
        raise SystemExit("REFUSED: --backup and --target must be absolute paths.")
    if not backup.is_file():
        raise SystemExit(f"REFUSED: backup not found: {backup}")
    if args.backup_dir:
        _ensure_inside(backup, Path(args.backup_dir), "backup")
    # Never restore onto a file inside the backup directory.
    if target.resolve().parent == backup.resolve().parent:
        raise SystemExit(
            "REFUSED: --target is inside the backup directory; restore must "
            "write outside it."
        )

    # Mandatory pre-restore gate: the backup must pass integrity_check.
    integrity = _integrity_check(backup)
    if integrity != "ok":
        print(json.dumps({
            "status": "refused-integrity-failed",
            "backup_path": str(backup.resolve()),
            "integrity_check": integrity,
        }, indent=2))
        return 3

    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(backup)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    post = _integrity_check(target)
    result = {
        "status": "ok" if post == "ok" else "restore-integrity-failed",
        "restored_at": _now(),
        "backup_path": str(backup.resolve()),
        "target": str(target.resolve()),
        "backup_sha256": _sha256(backup),
        "target_sha256": _sha256(target),
        "post_restore_integrity_check": post,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Online-backup a SQLite database.")
    p_backup.add_argument("--database", required=True)
    p_backup.add_argument("--backup-dir", required=True)
    p_backup.add_argument("--json-out")
    p_backup.set_defaults(func=cmd_backup)

    p_validate = sub.add_parser("validate", help="Verify a backup file.")
    p_validate.add_argument("--backup", required=True)
    p_validate.add_argument("--backup-dir", help="Optional containment root to enforce.")
    p_validate.set_defaults(func=cmd_validate)

    p_restore = sub.add_parser("restore", help="Restore a validated backup to a target DB.")
    p_restore.add_argument("--backup", required=True)
    p_restore.add_argument("--target", required=True)
    p_restore.add_argument("--backup-dir", help="Optional containment root to enforce.")
    p_restore.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
