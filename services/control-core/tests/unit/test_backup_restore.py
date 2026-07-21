"""Tests for database backup and restore — BackupService and admin API."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from packages.admin.backup_service import BackupError, BackupService, RestoreError

# ── Helpers ───────────────────────────────────────────────────────────────


def _create_test_db(path: str) -> None:
    """Create a small valid SQLite database at *path*."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO test_table (value) VALUES ('hello')")
    conn.commit()
    conn.close()


def _create_non_sqlite_file(path: str) -> None:
    """Create a file that is NOT a valid SQLite database."""
    Path(path).write_text("this is not a sqlite database", encoding="utf-8")


# ── BackupService Tests ───────────────────────────────────────────────────


class TestBackupServiceCreateBackup:
    """Tests for BackupService.create_backup."""

    def test_create_backup_success(self, tmp_path: Path) -> None:
        """Backup is created with correct filename pattern."""
        db_path = str(tmp_path / "agent_platform.db")
        backup_dir = str(tmp_path / "backups")
        _create_test_db(db_path)

        result = BackupService.create_backup(f"sqlite:///{db_path}", backup_dir)

        assert result.endswith(".db")
        assert "agent_platform_" in result
        assert Path(result).exists()

    def test_create_backup_file_content_matches(self, tmp_path: Path) -> None:
        """Backup file has the same content as the original DB."""
        db_path = str(tmp_path / "agent_platform.db")
        backup_dir = str(tmp_path / "backups")
        _create_test_db(db_path)

        result = BackupService.create_backup(f"sqlite:///{db_path}", backup_dir)

        # Verify the backup is a valid SQLite file with the same data
        conn = sqlite3.connect(result)
        rows = conn.execute("SELECT value FROM test_table").fetchall()
        conn.close()
        assert rows == [("hello",)]

    def test_create_backup_creates_directory(self, tmp_path: Path) -> None:
        """Backup directory is created if it doesn't exist."""
        db_path = str(tmp_path / "agent_platform.db")
        backup_dir = str(tmp_path / "nested" / "backups")
        _create_test_db(db_path)

        BackupService.create_backup(f"sqlite:///{db_path}", backup_dir)

        assert Path(backup_dir).exists()
        assert len(list(Path(backup_dir).glob("*.db"))) == 1

    def test_create_backup_db_not_exists(self, tmp_path: Path) -> None:
        """Raises BackupError when the source database doesn't exist."""
        db_path = str(tmp_path / "nonexistent.db")
        backup_dir = str(tmp_path / "backups")

        with pytest.raises(BackupError, match="does not exist"):
            BackupService.create_backup(f"sqlite:///{db_path}", backup_dir)

    def test_create_backup_unsupported_scheme(self, tmp_path: Path) -> None:
        """Raises BackupError for non-sqlite URLs."""
        backup_dir = str(tmp_path / "backups")

        with pytest.raises(BackupError, match="Unsupported"):
            BackupService.create_backup("postgresql://localhost/mydb", backup_dir)


class TestBackupServiceRestore:
    """Tests for BackupService.restore_backup."""

    def test_restore_backup_success(self, tmp_path: Path) -> None:
        """Restore overwrites the target database from a backup."""
        db_path = str(tmp_path / "agent_platform.db")
        backup_dir = str(tmp_path / "backups")
        _create_test_db(db_path)

        # Create backup
        backup_path = BackupService.create_backup(f"sqlite:///{db_path}", backup_dir)

        # Modify the original DB
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO test_table (value) VALUES ('modified')")
        conn.commit()
        conn.close()

        # Restore from backup
        result = BackupService.restore_backup(f"sqlite:///{db_path}", backup_path)

        assert result is True

        # Verify the restored data matches the backup (not the modification)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT value FROM test_table").fetchall()
        conn.close()
        assert rows == [("hello",)]

    def test_restore_backup_not_exists(self, tmp_path: Path) -> None:
        """Raises RestoreError when backup file doesn't exist."""
        db_path = str(tmp_path / "agent_platform.db")
        backup_path = str(tmp_path / "backups" / "nonexistent.db")

        with pytest.raises(RestoreError, match="does not exist"):
            BackupService.restore_backup(f"sqlite:///{db_path}", backup_path)

    def test_restore_backup_invalid_sqlite(self, tmp_path: Path) -> None:
        """Raises RestoreError when the backup file is not valid SQLite."""
        db_path = str(tmp_path / "agent_platform.db")
        fake_backup = str(tmp_path / "fake_backup.db")
        _create_non_sqlite_file(fake_backup)

        with pytest.raises(RestoreError, match="Invalid SQLite"):
            BackupService.restore_backup(f"sqlite:///{db_path}", fake_backup)


class TestBackupServiceListBackups:
    """Tests for BackupService.list_backups."""

    def test_list_backups_empty(self, tmp_path: Path) -> None:
        """Returns empty list when no backups directory exists."""
        backup_dir = str(tmp_path / "nonexistent_backups")
        result = BackupService.list_backups(backup_dir)
        assert result == []

    def test_list_backups_returns_all(self, tmp_path: Path) -> None:
        """Lists all backup files with correct metadata."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)

        # Create two valid backup files
        _create_test_db(str(tmp_path / "backups" / "agent_platform_20260101_000000.db"))
        _create_test_db(str(tmp_path / "backups" / "agent_platform_20260102_120000.db"))

        result = BackupService.list_backups(backup_dir)

        assert len(result) == 2
        for b in result:
            assert "id" in b
            assert "filename" in b
            assert "path" in b
            assert "size_bytes" in b
            assert "created_at" in b

    def test_list_backups_sorted_newest_first(self, tmp_path: Path) -> None:
        """Backups are sorted with newest first."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)

        _create_test_db(str(tmp_path / "backups" / "agent_platform_20260101_000000.db"))
        _create_test_db(str(tmp_path / "backups" / "agent_platform_20260102_120000.db"))

        result = BackupService.list_backups(backup_dir)

        # The second file was created later, so it should be first
        assert result[0]["id"] == "agent_platform_20260102_120000"
        assert result[1]["id"] == "agent_platform_20260101_000000"

    def test_list_backups_ignores_non_matching_files(self, tmp_path: Path) -> None:
        """Only agent_platform_*.db files are listed."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)

        _create_test_db(str(tmp_path / "backups" / "agent_platform_20260101_000000.db"))
        _create_non_sqlite_file(str(tmp_path / "backups" / "other_file.txt"))
        _create_non_sqlite_file(str(tmp_path / "backups" / "agent_platform_notes.txt"))

        result = BackupService.list_backups(backup_dir)
        assert len(result) == 1


class TestBackupServiceDelete:
    """Tests for BackupService.delete_backup."""

    def test_delete_backup_success(self, tmp_path: Path) -> None:
        """Deletes an existing backup file."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = str(tmp_path / "backups" / "agent_platform_20260101_000000.db")
        _create_test_db(backup_file)

        result = BackupService.delete_backup(backup_file, backup_dir)

        assert result is True
        assert not Path(backup_file).exists()

    def test_delete_backup_not_found(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when backup doesn't exist."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = str(tmp_path / "backups" / "nonexistent.db")

        with pytest.raises(FileNotFoundError):
            BackupService.delete_backup(backup_file, backup_dir)


class TestBackupServicePathTraversal:
    """Tests for path traversal protection."""

    def test_delete_backup_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Cannot delete files outside the backup directory via path traversal."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)

        # Try to reference a file outside backup_dir using ../
        target = str(tmp_path / "sensitive_file.txt")
        Path(target).write_text("secret data", encoding="utf-8")

        with pytest.raises(BackupError, match="resolves outside"):
            BackupService.delete_backup(target, backup_dir)

        # Ensure the file was NOT deleted
        assert Path(target).exists()

    def test_delete_backup_absolute_path_outside_dir(self, tmp_path: Path) -> None:
        """Cannot delete arbitrary files via absolute paths."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)

        # Create a file completely outside the backup tree
        other_file = str(tmp_path / "other_dir" / "important.db")
        os.makedirs(str(tmp_path / "other_dir"), exist_ok=True)
        _create_test_db(other_file)

        with pytest.raises(BackupError, match="resolves outside"):
            BackupService.delete_backup(other_file, backup_dir)

        assert Path(other_file).exists()


# ── Admin API Tests ───────────────────────────────────────────────────────


class TestAdminBackupAPI:
    """Tests for the admin backup/restore API endpoints."""

    @pytest.fixture()
    def setup(self, tmp_path: Path):
        """Create a test FastAPI app with a temp database and return test helpers."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from apps.api_server.routes.admin import router as admin_router

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = str(data_dir / "agent_platform.db")
        backup_dir = str(data_dir / "backups")
        _create_test_db(db_path)

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")

        from apps.api_server.dependencies import _resolve_current_user
        from apps.api_server.dependencies import get_db as _get_db_dep

        def _mock_get_db():
            yield None

        app.dependency_overrides[_get_db_dep] = _mock_get_db

        from packages.db.models import User, UserRole

        fake_user = User(
            id="test-admin",
            username="admin",
            email=None,
            hashed_password="",
            role=UserRole.ADMIN,
            is_active=True,
        )

        def _mock_current_user():
            return fake_user

        app.dependency_overrides[_resolve_current_user] = _mock_current_user

        client = TestClient(app)

        # Patch settings so the API uses our temp paths
        from packages.config import DatabaseSettings, SecuritySettings, Settings

        fake_settings = Settings(
            database=DatabaseSettings(url=f"sqlite:///{db_path}"),
            security=SecuritySettings(require_auth=False),
        )

        return {
            "client": client,
            "settings": fake_settings,
            "db_path": db_path,
            "backup_dir": backup_dir,
            "tmp_path": tmp_path,
        }

    def test_create_backup_endpoint(self, setup) -> None:
        """POST /api/v1/admin/backup creates a backup and returns its path."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            response = client.post("/api/v1/admin/backup")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "backup_path" in data["data"]
        assert Path(data["data"]["backup_path"]).exists()

    def test_list_backups_endpoint(self, setup) -> None:
        """GET /api/v1/admin/backups lists available backups."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            # Create a backup first
            client.post("/api/v1/admin/backup")
            # List backups
            response = client.get("/api/v1/admin/backups")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 1
        assert len(data["data"]["backups"]) == 1

    def test_restore_backup_endpoint(self, setup) -> None:
        """POST /api/v1/admin/restore restores from a backup file."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]
        db_path = setup["db_path"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            # Create backup
            backup_resp = client.post("/api/v1/admin/backup")
            backup_path = backup_resp.json()["data"]["backup_path"]

            # Modify the DB
            conn = sqlite3.connect(db_path)
            conn.execute("INSERT INTO test_table (value) VALUES ('after_backup')")
            conn.commit()
            conn.close()

            # Restore
            restore_resp = client.post(
                "/api/v1/admin/restore",
                json={"backup_path": backup_path},
            )

        assert restore_resp.status_code == 200
        assert restore_resp.json()["success"] is True

        # Verify data was restored (modification should be gone)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT value FROM test_table").fetchall()
        conn.close()
        assert rows == [("hello",)]

    def test_restore_invalid_file(self, setup) -> None:
        """POST /api/v1/admin/restore returns 400 for invalid backup file."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            response = client.post(
                "/api/v1/admin/restore",
                json={"backup_path": str(setup["tmp_path"] / "nonexistent.db")},
            )

        assert response.status_code == 400

    def test_delete_backup_endpoint(self, setup) -> None:
        """DELETE /api/v1/admin/backups/{backup_id} deletes a backup."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            # Create backup
            backup_resp = client.post("/api/v1/admin/backup")
            backup_path = backup_resp.json()["data"]["backup_path"]
            backup_id = Path(backup_path).stem  # e.g. "agent_platform_20260512_120000"

            # Delete it
            del_resp = client.delete(f"/api/v1/admin/backups/{backup_id}")

        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True
        assert not Path(backup_path).exists()

    def test_delete_backup_not_found(self, setup) -> None:
        """DELETE returns 404 when backup doesn't exist."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            response = client.delete("/api/v1/admin/backups/agent_platform_99999999_999999")

        assert response.status_code == 404

    def test_list_backups_empty_dir(self, setup) -> None:
        """GET /api/v1/admin/backups returns empty list when no backups exist."""
        client = setup["client"]
        fake_settings = setup["settings"]
        backup_dir = setup["backup_dir"]

        with (
            patch("apps.api_server.routes.admin.get_settings", return_value=fake_settings),
            patch("apps.api_server.routes.admin._get_backup_dir", return_value=backup_dir),
            patch("apps.api_server.dependencies.get_settings", return_value=fake_settings),
        ):
            response = client.get("/api/v1/admin/backups")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 0
        assert data["data"]["backups"] == []
