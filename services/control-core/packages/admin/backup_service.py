"""SQLite database backup and restore service.

Provides safe file-copy based backup/restore with path traversal protection
and SQLite file validation.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_backup_lock = threading.Lock()


class BackupError(Exception):
    """Raised when a backup operation fails."""


class RestoreError(Exception):
    """Raised when a restore operation fails."""


class BackupService:
    """Service for creating, restoring, listing, and deleting SQLite backups.

    Backup files are stored as simple file copies with a timestamped filename
    in the specified backup directory.
    """

    @staticmethod
    def _db_path_from_url(db_url: str) -> Path:
        """Extract the filesystem path from a SQLAlchemy database URL.

        Handles ``sqlite:///./relative/path`` and ``sqlite:////absolute/path``.
        """
        # Remove the sqlite:/// prefix
        url = db_url.strip()
        if url.startswith("sqlite:///"):
            return Path(url[len("sqlite:///"):])
        if url.startswith("sqlite://"):
            return Path(url[len("sqlite://"):])
        raise BackupError(f"Unsupported database URL scheme: {db_url}")

    @staticmethod
    def _validate_sqlite_file(path: Path) -> bool:
        """Check whether *path* points to a valid SQLite database file."""
        try:
            conn = sqlite3.connect(str(path))
            try:
                conn.execute("PRAGMA integrity_check")
                # A second quick sanity check — try to read sqlite_version
                conn.execute("SELECT sqlite_version()")
            finally:
                conn.close()
            return True
        except Exception as e:
            logger.warning("SQLite validation failed for %s: %s", path, e)
            return False

    @staticmethod
    def _validate_within_dir(path: Path, directory: Path) -> None:
        """Ensure *path* is a child of *directory* after resolving both.

        Raises :class:`BackupError` if the path escapes the directory.
        """
        resolved = path.resolve()
        dir_resolved = directory.resolve()
        # Check if resolved is the same as or a child of dir_resolved.
        # Use .is_relative_to() (Python 3.9+) which handles platform separators.
        try:
            if not resolved.is_relative_to(dir_resolved):
                raise BackupError(
                    f"Path '{path}' resolves outside the backup directory '{directory}'"
                )
        except AttributeError:
            # Fallback for older Python
            dir_str = str(dir_resolved).rstrip("/\\")
            if str(resolved) != dir_str and not str(resolved).startswith(dir_str + "/") and not str(resolved).startswith(dir_str + "\\"):
                raise BackupError(
                    f"Path '{path}' resolves outside the backup directory '{directory}'"
                )

    @staticmethod
    def create_backup(db_url: str, backup_dir: str) -> str:
        with _backup_lock:
            source_path = BackupService._db_path_from_url(db_url)
            backup_path = Path(backup_dir)

            backup_path.mkdir(parents=True, exist_ok=True)

            if not source_path.exists():
                raise BackupError(f"Database file does not exist: {source_path}")

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            backup_file = backup_path / f"agent_platform_{timestamp}.db"

            source_conn = sqlite3.connect(str(source_path))
            try:
                target_conn = sqlite3.connect(str(backup_file))
                try:
                    source_conn.backup(target_conn)
                finally:
                    target_conn.close()
            finally:
                source_conn.close()
            return str(backup_file)

    @staticmethod
    def restore_backup(db_url: str, backup_path: str, backup_dir: str | None = None) -> bool:
        """Restore the database from a backup file.

        The backup file must exist, be within the backup directory, and be a
        valid SQLite database.

        Args:
            db_url: SQLAlchemy database URL (must be sqlite).
            backup_path: Path to the backup file to restore from.
            backup_dir: Allowed backup directory for traversal protection.
                When provided, the backup file must reside within this directory.

        Returns:
            True if the restore succeeded.

        Raises:
            RestoreError: If validation fails or copy fails.
        """
        source = Path(backup_path).resolve()

        if backup_dir is not None:
            BackupService._validate_within_dir(source, Path(backup_dir).resolve())

        target = BackupService._db_path_from_url(db_url)

        if not source.exists():
            raise RestoreError(f"Backup file does not exist: {backup_path}")

        if not BackupService._validate_sqlite_file(source):
            raise RestoreError(f"Invalid SQLite file: {backup_path}")

        # Ensure the target directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(str(source), str(target))
        return True

    @staticmethod
    def list_backups(backup_dir: str) -> list[dict[str, Any]]:
        """List all backup files in the backup directory.

        Returns a list of dicts sorted by modification time (newest first),
        each containing ``id``, ``filename``, ``path``, ``size_bytes``,
        and ``created_at``.

        Integrity validation is intentionally omitted here for performance;
        use :meth:`validate_backup` for on-demand checks.
        """
        backup_path = Path(backup_dir)
        if not backup_path.exists():
            return []

        backups: list[dict[str, Any]] = []
        for f in sorted(backup_path.glob("agent_platform_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = f.stat()
            backups.append({
                "id": f.stem,  # e.g. "agent_platform_20260512_120000"
                "filename": f.name,
                "path": str(f),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            })
        return backups

    @staticmethod
    def validate_backup(backup_path: str) -> dict[str, Any]:
        """Validate a single backup file's SQLite integrity on demand.

        Args:
            backup_path: Path to the backup file.

        Returns:
            Dict with ``path`` and ``is_valid_sqlite`` keys.
        """
        source = Path(backup_path)
        if not source.exists():
            raise FileNotFoundError(f"Backup file does not exist: {backup_path}")
        return {
            "path": str(source),
            "is_valid_sqlite": BackupService._validate_sqlite_file(source),
        }

    @staticmethod
    def delete_backup(backup_path: str, backup_dir: str) -> bool:
        """Delete a specific backup file.

        Args:
            backup_path: Path to the backup file to delete.
            backup_dir: The allowed backup directory (for traversal protection).

        Returns:
            True if the file was deleted.

        Raises:
            BackupError: If the path escapes the backup directory.
            FileNotFoundError: If the backup file does not exist.
        """
        target = Path(backup_path).resolve()
        dir_path = Path(backup_dir).resolve()

        BackupService._validate_within_dir(target, dir_path)

        if not target.exists():
            raise FileNotFoundError(f"Backup file does not exist: {backup_path}")

        target.unlink()
        return True
