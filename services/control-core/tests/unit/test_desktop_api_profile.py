"""Regression coverage for the lightweight desktop Sidecar API profile."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CONTROL_CORE = Path(__file__).resolve().parents[2]


def test_desktop_profile_registers_only_required_routes(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'profile.db').as_posix()}",
            "LLM_PROVIDER": "mock",
            "PYTHONDONTWRITEBYTECODE": "1",
            "REQUIRE_AUTH": "true",
            "SECRET_KEY": "desktop-profile-test-secret-key-32chars",
            "TESTING": "1",
            "ZCODE_API_PROFILE": "desktop",
        }
    )
    script = """
import json
from apps.api_server.main import app

paths = sorted(app.openapi()["paths"])
print("ZCODE_DESKTOP_ROUTES=" + json.dumps(paths), flush=True)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=CONTROL_CORE,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    marker = next(
        line for line in completed.stdout.splitlines() if line.startswith("ZCODE_DESKTOP_ROUTES=")
    )
    paths = set(json.loads(marker.removeprefix("ZCODE_DESKTOP_ROUTES=")))

    assert "/health" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/tasks" in paths
    assert "/api/v1/approvals" in paths
    assert "/api/v1/gateway-approvals" in paths
    assert "/api/v1/graphql" not in paths
    assert "/api/v1/marketplace" not in paths
    assert "/api/v1/metrics" not in paths
