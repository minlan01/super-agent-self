"""Backup & Recovery Service (spec §P1.5 + §P3.6).

Provides:
  - create_backup(): timestamped snapshot of SQLite DB + workspace
  - list_backups(): enumerate available backups
  - restore_backup(): restore from a specific backup ID
  - verify_backup(): integrity check (checksum + DB pragma)

Design:
  - Backups are stored in data/backups/<timestamp>/
  - Each backup contains: control.db copy, workspace snapshot, manifest.json
  - SQLite backup uses VACUUM INTO (atomic, doesn't block writers)
  - Restore copies files back and runs integrity_check
  - Manifest records: backup_id, timestamp, db_size, file_count, checksums

Security:
  - Backups exclude secrets (Credential Manager entries stay in OS keychain)
  - Manifest contains checksums for tamper detection
  - Restore verifies checksums before overwriting
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

_DEFAULT_BACKUP_ROOT = "data/backups"
_DEFAULT_DB_PATH = "data/agent_platform.db"
_DEFAULT_WORKSPACE = "workspace"


class BackupStatus(str, Enum):
    CREATED = "created"
    RESTORED = "restored"
    VERIFIED = "verified"
    FAILED = "failed"
    CORRUPT = "corrupt"


@dataclass
class BackupManifest:
    """Metadata for a single backup."""
    backup_id: str
    timestamp: str
    db_path: str
    db_size: int
    db_checksum: str
    workspace_files: int = 0
    workspace_checksum: str = ""
    status: BackupStatus = BackupStatus.CREATED
    created_by: str = "system"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "timestamp": self.timestamp,
            "db_path": self.db_path,
            "db_size": self.db_size,
            "db_checksum": self.db_checksum,
            "workspace_files": self.workspace_files,
            "workspace_checksum": self.workspace_checksum,
            "status": self.status.value,
            "created_by": self.created_by,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BackupManifest":
        return cls(
            backup_id=d["backup_id"],
            timestamp=d["timestamp"],
            db_path=d["db_path"],
            db_size=d["db_size"],
            db_checksum=d["db_checksum"],
            workspace_files=d.get("workspace_files", 0),
            workspace_checksum=d.get("workspace_checksum", ""),
            status=BackupStatus(d.get("status", "created")),
            created_by=d.get("created_by", "system"),
            notes=d.get("notes", ""),
        )


class BackupService:
    """Manages timestamped backups of DB + workspace.

    Usage:
        svc = BackupService()
        manifest = svc.create_backup()
        backups = svc.list_backups()
        svc.restore_backup(manifest.backup_id)
    """

    def __init__(
        self,
        backup_root: str | Path = _DEFAULT_BACKUP_ROOT,
        db_path: str | Path = _DEFAULT_DB_PATH,
        workspace: str | Path = _DEFAULT_WORKSPACE,
    ):
        self.backup_root = Path(backup_root)
        self.db_path = Path(db_path)
        self.workspace = Path(workspace)
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        *,
        created_by: str = "system",
        notes: str = "",
        include_workspace: bool = True,
    ) -> BackupManifest:
        """Create a timestamped backup.

        Uses SQLite VACUUM INTO for an atomic, non-blocking DB copy.
        Workspace is copied with shutil (best-effort, may be large).
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        # Append milliseconds + short random suffix to avoid collision
        # when multiple backups are created within the same second.
        ms = datetime.now(UTC).strftime("%f")[:3]
        backup_id = f"backup-{timestamp}-{ms}"
        backup_dir = self.backup_root / backup_id

        # If somehow still collides, append a counter.
        counter = 0
        while backup_dir.exists():
            counter += 1
            backup_id = f"backup-{timestamp}-{ms}-{counter}"
            backup_dir = self.backup_root / backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Backup SQLite DB (atomic via VACUUM INTO) ──
        db_backup_path = backup_dir / "control.db"

        # Remove stale backup file if it exists (VACUUM INTO requires fresh target).
        if db_backup_path.exists():
            db_backup_path.unlink()

        if self.db_path.exists():
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute(f"VACUUM INTO '{db_backup_path}'")
            finally:
                conn.close()

            db_size = db_backup_path.stat().st_size
            db_checksum = self._file_checksum(db_backup_path)
        else:
            db_size = 0
            db_checksum = ""

        # ── 2. Backup workspace (optional) ──
        ws_files = 0
        ws_checksum = ""
        if include_workspace and self.workspace.exists():
            ws_backup_dir = backup_dir / "workspace"
            ws_files = self._copy_tree(self.workspace, ws_backup_dir)
            ws_checksum = self._dir_checksum(ws_backup_dir)

        # ── 3. Write manifest ──
        manifest = BackupManifest(
            backup_id=backup_id,
            timestamp=timestamp,
            db_path=str(db_backup_path),
            db_size=db_size,
            db_checksum=db_checksum,
            workspace_files=ws_files,
            workspace_checksum=ws_checksum,
            status=BackupStatus.CREATED,
            created_by=created_by,
            notes=notes,
        )

        manifest_path = backup_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest.to_dict(), f, indent=2)

        logger.info(
            "Backup created: id=%s db_size=%d ws_files=%d",
            backup_id, db_size, ws_files,
        )
        return manifest

    def list_backups(self) -> list[BackupManifest]:
        """List all available backups, sorted by timestamp (newest first)."""
        backups = []
        for entry in self.backup_root.iterdir():
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path) as f:
                    data = json.load(f)
                backups.append(BackupManifest.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Corrupt manifest in %s: %s", entry, e)
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        return backups

    def get_backup(self, backup_id: str) -> BackupManifest | None:
        """Get a specific backup manifest by ID."""
        manifest_path = self.backup_root / backup_id / "manifest.json"
        if not manifest_path.exists():
            return None
        with open(manifest_path) as f:
            return BackupManifest.from_dict(json.load(f))

    def verify_backup(self, backup_id: str) -> BackupStatus:
        """Verify a backup's integrity (checksums + DB pragma).

        Returns:
            VERIFIED if all checks pass.
            CORRUPT if checksums don't match or DB is corrupt.
            FAILED if backup doesn't exist.
        """
        manifest = self.get_backup(backup_id)
        if manifest is None:
            return BackupStatus.FAILED

        backup_dir = self.backup_root / backup_id

        # Check DB checksum.
        db_path = backup_dir / "control.db"
        if db_path.exists():
            actual_checksum = self._file_checksum(db_path)
            if actual_checksum != manifest.db_checksum:
                logger.error(
                    "Backup DB checksum mismatch: expected=%s actual=%s",
                    manifest.db_checksum, actual_checksum,
                )
                return BackupStatus.CORRUPT

            # Check DB integrity.
            conn = sqlite3.connect(str(db_path))
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()
                if result[0] != "ok":
                    logger.error("Backup DB integrity check failed: %s", result[0])
                    return BackupStatus.CORRUPT
            finally:
                conn.close()
        else:
            return BackupStatus.CORRUPT

        return BackupStatus.VERIFIED

    def restore_backup(
        self,
        backup_id: str,
        *,
        overwrite_current: bool = False,
    ) -> BackupStatus:
        """Restore from a backup.

        Verifies checksums before overwriting. Does NOT overwrite the current
        DB unless overwrite_current=True (safety guard).
        """
        if not overwrite_current:
            logger.warning(
                "Restore requested but overwrite_current=False — dry run only. "
                "Set overwrite_current=True to actually restore."
            )
            return self.verify_backup(backup_id)

        manifest = self.get_backup(backup_id)
        if manifest is None:
            return BackupStatus.FAILED

        # Verify before restore.
        status = self.verify_backup(backup_id)
        if status != BackupStatus.VERIFIED:
            logger.error("Backup verification failed, aborting restore: %s", status)
            return status

        backup_dir = self.backup_root / backup_id

        # ── Restore DB ──
        db_backup = backup_dir / "control.db"
        if db_backup.exists() and self.db_path.exists():
            # Copy current DB as a pre-restore safety net.
            safety = self.db_path.with_suffix(".db.pre-restore")
            shutil.copy2(str(self.db_path), str(safety))

            # Restore.
            shutil.copy2(str(db_backup), str(self.db_path))
            logger.info("DB restored from %s", backup_id)

        # ── Restore workspace ──
        ws_backup = backup_dir / "workspace"
        if ws_backup.exists():
            if self.workspace.exists():
                shutil.rmtree(str(self.workspace))
            shutil.copytree(str(ws_backup), str(self.workspace))
            logger.info("Workspace restored from %s", backup_id)

        return BackupStatus.RESTORED

    def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup."""
        backup_dir = self.backup_root / backup_id
        if not backup_dir.exists():
            return False
        shutil.rmtree(str(backup_dir))
        logger.info("Backup deleted: %s", backup_id)
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _file_checksum(path: Path) -> str:
        """SHA-256 of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _dir_checksum(path: Path) -> str:
        """Aggregate SHA-256 of all files in a directory (sorted)."""
        h = hashlib.sha256()
        for root, _dirs, files in os.walk(str(path)):
            for name in sorted(files):
                fpath = Path(root) / name
                h.update(str(fpath.relative_to(path)).encode())
                with open(fpath, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _copy_tree(src: Path, dst: Path) -> int:
        """Copy a directory tree, return file count."""
        dst.mkdir(parents=True, exist_ok=True)
        count = 0
        for root, _dirs, files in os.walk(str(src)):
            rel = Path(root).relative_to(src)
            target = dst / rel
            target.mkdir(parents=True, exist_ok=True)
            for name in files:
                shutil.copy2(
                    str(Path(root) / name),
                    str(target / name),
                )
                count += 1
        return count
