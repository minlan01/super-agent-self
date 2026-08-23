"""Generate the empty Alembic-head SQLite database bundled with the Sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command

DATABASE_NAME = "agent_platform.db"
MANIFEST_NAME = "manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _validate_empty_head_database(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("generated bootstrap failed PRAGMA quick_check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("generated bootstrap failed PRAGMA foreign_key_check")
        revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(revisions) != 1 or not isinstance(revisions[0][0], str) or not revisions[0][0]:
            raise RuntimeError("generated bootstrap has an invalid Alembic revision")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        ]
        populated = []
        for table in tables:
            quoted = table.replace('"', '""')
            count = connection.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
            if count:
                populated.append((table, count))
        if populated:
            raise RuntimeError(f"generated bootstrap contains application data: {populated}")
        connection.execute("VACUUM")
        return revisions[0][0]


def generate(resource_root: Path, output_dir: Path) -> dict[str, object]:
    resource_root = resource_root.resolve()
    output_dir = output_dir.resolve()
    if not (resource_root / "alembic").is_dir():
        raise RuntimeError(f"missing Alembic scripts under {resource_root}")
    output_dir.mkdir(parents=True, exist_ok=True)
    database = output_dir / DATABASE_NAME
    manifest_path = output_dir / MANIFEST_NAME
    database.unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)

    database_url = "sqlite:///" + database.as_posix()
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
    config = Config()
    config.set_main_option("script_location", str(resource_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    try:
        command.upgrade(config, "head")
        revision = _validate_empty_head_database(database)
        manifest: dict[str, object] = {
            "format": 1,
            "database": DATABASE_NAME,
            "revision": revision,
            "size": database.stat().st_size,
            "sha256": _sha256(database),
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest
    except Exception:
        database.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.resource_root, args.output_dir), indent=2))


if __name__ == "__main__":
    main()

