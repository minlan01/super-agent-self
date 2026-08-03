"""Tests for BackupService (P3.7) — create, verify, restore."""

import os
import sqlite3
import tempfile

import pytest

from packages.platform.backup_service import (
    BackupService,
    BackupStatus,
)


@pytest.fixture()
def env():
    """Create temp DB + workspace + backup root."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        ws_path = os.path.join(tmpdir, "workspace")
        backup_root = os.path.join(tmpdir, "backups")

        # Create a real SQLite DB with some data.
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test (id INTEGER, data TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.execute("INSERT INTO test VALUES (2, 'world')")
        conn.commit()
        conn.close()

        # Create workspace with files.
        os.makedirs(os.path.join(ws_path, "subdir"))
        with open(os.path.join(ws_path, "file1.txt"), "w") as f:
            f.write("content1")
        with open(os.path.join(ws_path, "subdir", "file2.txt"), "w") as f:
            f.write("content2")

        svc = BackupService(
            backup_root=backup_root,
            db_path=db_path,
            workspace=ws_path,
        )
        yield svc, db_path, ws_path


class TestBackupService:
    def test_create_backup(self, env):
        svc, db_path, _ = env
        manifest = svc.create_backup(notes="test backup")
        assert manifest.backup_id.startswith("backup-")
        assert manifest.status == BackupStatus.CREATED
        assert manifest.db_size > 0
        assert len(manifest.db_checksum) == 64  # SHA-256 hex
        assert manifest.workspace_files >= 2

    def test_list_backups_sorted(self, env):
        svc, _, _ = env
        svc.create_backup()
        svc.create_backup()
        backups = svc.list_backups()
        assert len(backups) == 2
        # Sorted newest first
        assert backups[0].timestamp >= backups[1].timestamp

    def test_get_backup_by_id(self, env):
        svc, _, _ = env
        m = svc.create_backup()
        fetched = svc.get_backup(m.backup_id)
        assert fetched is not None
        assert fetched.backup_id == m.backup_id

    def test_get_nonexistent_backup(self, env):
        svc, _, _ = env
        assert svc.get_backup("nonexistent") is None

    def test_verify_backup_passes(self, env):
        svc, _, _ = env
        m = svc.create_backup()
        status = svc.verify_backup(m.backup_id)
        assert status == BackupStatus.VERIFIED

    def test_verify_corrupt_backup(self, env):
        svc, _, _ = env
        m = svc.create_backup()
        # Corrupt the DB backup.
        backup_db = svc.backup_root / m.backup_id / "control.db"
        with open(backup_db, "r+b") as f:
            f.seek(100)
            f.write(b"CORRUPT")
        status = svc.verify_backup(m.backup_id)
        assert status == BackupStatus.CORRUPT

    def test_restore_dry_run(self, env):
        """Restore without overwrite_current just verifies."""
        svc, _, _ = env
        m = svc.create_backup()
        status = svc.restore_backup(m.backup_id, overwrite_current=False)
        assert status == BackupStatus.VERIFIED

    def test_restore_overwrites_db(self, env):
        svc, db_path, _ = env
        m = svc.create_backup()

        # Modify current DB.
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO test VALUES (99, 'modified')")
        conn.commit()
        conn.close()

        # Verify modification.
        conn = sqlite3.connect(db_path)
        count_before = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
        conn.close()
        assert count_before == 3  # 2 original + 1 new

        # Restore.
        status = svc.restore_backup(m.backup_id, overwrite_current=True)
        assert status == BackupStatus.RESTORED

        # Verify DB is back to original (2 rows, no row 99).
        conn = sqlite3.connect(db_path)
        count_after = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
        row99 = conn.execute("SELECT * FROM test WHERE id=99").fetchone()
        conn.close()
        assert count_after == 2
        assert row99 is None

    def test_restore_creates_safety_copy(self, env):
        svc, db_path, _ = env
        m = svc.create_backup()
        svc.restore_backup(m.backup_id, overwrite_current=True)
        # Safety copy should exist.
        safety = db_path.replace(".db", ".db.pre-restore") \
            if not db_path.endswith(".db.pre-restore") else db_path
        # The safety file path is db_path + ".pre-restore" replacement.
        safety_path = db_path.replace(".db", ".db.pre-restore")
        assert os.path.exists(safety_path)

    def test_delete_backup(self, env):
        svc, _, _ = env
        m = svc.create_backup()
        assert svc.delete_backup(m.backup_id) is True
        assert svc.get_backup(m.backup_id) is None
        # Second delete returns False.
        assert svc.delete_backup(m.backup_id) is False

    def test_backup_excludes_no_secrets_column(self, env):
        """Backups should not contain Credential Manager data (by design)."""
        svc, _, _ = env
        m = svc.create_backup()
        # The manifest should not have any 'secret' or 'credential' fields.
        manifest_data = m.to_dict()
        manifest_str = str(manifest_data).lower()
        assert "password" not in manifest_str
        assert "api_key" not in manifest_str

    def test_workspace_restore(self, env):
        svc, _, ws_path = env
        m = svc.create_backup()

        # Delete a workspace file.
        os.remove(os.path.join(ws_path, "file1.txt"))
        assert not os.path.exists(os.path.join(ws_path, "file1.txt"))

        # Restore.
        svc.restore_backup(m.backup_id, overwrite_current=True)

        # File should be back.
        assert os.path.exists(os.path.join(ws_path, "file1.txt"))
