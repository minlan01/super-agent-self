"""Tests for the packaged SQLite bootstrap used by the Windows Sidecar."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from packages.platform.windows.sidecar_host import _bootstrap_sqlite_if_current


def test_sidecar_host_import_does_not_eager_load_windows_adapters() -> None:
    script = """
import json
import sys
import packages.platform.windows.sidecar_host

blocked = [
    name for name in sys.modules
    if name in {
        "packages.platform.windows.adapter",
        "packages.platform.windows.capture_wgc",
        "packages.platform.windows.process_sandbox",
        "packages.platform.windows.uia",
    }
]
print(json.dumps(blocked))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )

    assert json.loads(completed.stdout) == []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write_database(path: Path, revision: str, *, payload: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute("CREATE TABLE bootstrap_probe (value TEXT NOT NULL)")
        if payload is not None:
            connection.execute("INSERT INTO bootstrap_probe VALUES (?)", (payload,))


def _write_bootstrap(resource_root: Path, revision: str = "p4_head") -> Path:
    bootstrap_dir = resource_root / "bootstrap"
    database = bootstrap_dir / "agent_platform.db"
    _write_database(database, revision)
    manifest = {
        "format": 1,
        "database": database.name,
        "revision": revision,
        "size": database.stat().st_size,
        "sha256": _sha256(database),
    }
    (bootstrap_dir / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return database


def test_bootstrap_installs_verified_database_atomically(tmp_path: Path, monkeypatch) -> None:
    resource_root = tmp_path / "resources"
    source = _write_bootstrap(resource_root)
    target = tmp_path / "data" / "agent_platform.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")

    assert _bootstrap_sqlite_if_current(resource_root) is True
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob(".*.bootstrap-*"))


def test_bootstrap_rejects_tampered_database(tmp_path: Path, monkeypatch) -> None:
    resource_root = tmp_path / "resources"
    source = _write_bootstrap(resource_root)
    tampered = bytearray(source.read_bytes())
    tampered[-1] ^= 0xFF
    source.write_bytes(tampered)
    target = tmp_path / "data" / "agent_platform.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")

    with pytest.raises(RuntimeError, match="SHA-256"):
        _bootstrap_sqlite_if_current(resource_root)

    assert not target.exists()


def test_current_database_skips_migrations_without_replacing_user_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resource_root = tmp_path / "resources"
    _write_bootstrap(resource_root)
    target = tmp_path / "data" / "agent_platform.db"
    _write_database(target, "p4_head", payload="keep-me")
    before = target.read_bytes()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")

    assert _bootstrap_sqlite_if_current(resource_root) is True
    assert target.read_bytes() == before
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM bootstrap_probe").fetchone() == ("keep-me",)


def test_older_database_falls_back_to_standard_migrations(tmp_path: Path, monkeypatch) -> None:
    resource_root = tmp_path / "resources"
    _write_bootstrap(resource_root, revision="p4_head")
    target = tmp_path / "data" / "agent_platform.db"
    _write_database(target, "older_revision", payload="keep-me")
    before = target.read_bytes()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")

    assert _bootstrap_sqlite_if_current(resource_root) is False
    assert target.read_bytes() == before
