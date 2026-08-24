"""Unit tests for the license policy tool's fail-closed modes (GA-1.4).

Run: python -m pytest tools/license-policy/test_check_licenses.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_licenses  # noqa: E402


class TestPythonEntries:
    def test_zero_entries_fails(self):
        code, violations, count = check_licenses.python_violations_from_entries([])
        assert code == 1 and count == 0
        assert any("zero-components" in v for v in violations)

    def test_empty_license_fails(self):
        entries = [{"Name": "pkg-a", "Version": "1.0", "License": ""},
                   {"Name": "pkg-b", "Version": "1.0", "License": "MIT"}]
        code, violations, _ = check_licenses.python_violations_from_entries(entries)
        assert code == 1
        assert any("pkg-a" in v and "missing/empty" in v for v in violations)

    def test_unknown_spdx_fails(self):
        entries = [{"Name": "pkg-gpl", "Version": "1.0", "License": "GPL-3.0-only"}]
        code, violations, _ = check_licenses.python_violations_from_entries(entries)
        assert code == 1 and any("pkg-gpl" in v for v in violations)

    def test_agpl_and_sspl_denied(self):
        entries = [
            {"Name": "pkg-agpl", "Version": "1", "License": "AGPL-3.0-only"},
            {"Name": "pkg-sspl", "Version": "1", "License": "SSPL-1.0"},
        ]
        _, violations, _ = check_licenses.python_violations_from_entries(entries)
        assert any("pkg-agpl" in v and "copyleft-deny" in v for v in violations)
        assert any("pkg-sspl" in v and "copyleft-deny" in v for v in violations)

    def test_approved_dual_license_passes(self):
        entries = [{"Name": "pkg-ok", "Version": "1", "License": "MIT; Apache-2.0"}]
        code, violations, count = check_licenses.python_violations_from_entries(entries)
        assert code == 0 and violations == [] and count == 1


class TestNpmManifests:
    def test_zero_components_fails(self):
        code, violations, count = check_licenses.npm_violations_from_manifests([])
        assert code == 1 and count == 0
        assert any("zero-components" in v for v in violations)

    def test_missing_license_fails(self):
        manifests = [{"name": "vite", "version": "6.0.0", "license": ""}]
        code, violations, _ = check_licenses.npm_violations_from_manifests(manifests)
        assert code == 1
        assert any("vite@6.0.0" in v and "missing/empty" in v for v in violations)

    def test_sspl_denied(self):
        manifests = [
            {"name": "a", "version": "1.0", "license": "MIT"},
            {"name": "b", "version": "2.0", "license": "SSPL-1.0"},
        ]
        _, violations, _ = check_licenses.npm_violations_from_manifests(manifests)
        assert any("b@2.0" in v and "copyleft-deny" in v for v in violations)

    def test_approved_passes_with_count_and_dedupe(self):
        manifests = [
            {"name": "vite", "version": "6.0.0", "license": "MIT"},
            {"name": "esbuild", "version": "0.24.0", "license": "MIT"},
            {"name": "vite", "version": "6.0.0", "license": "MIT"},  # dup
        ]
        code, violations, count = check_licenses.npm_violations_from_manifests(manifests)
        assert code == 0 and violations == [] and count == 2

    def test_not_installed_dir_fails_closed(self, tmp_path):
        code, violations, _ = check_licenses.check_npm(tmp_path)
        assert code == 1
        assert any("npm-not-installed" in v for v in violations)

    def test_legacy_license_object_form_normalized(self, tmp_path):
        pkg = tmp_path / "node_modules" / "old-pkg"
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text(
            json.dumps({"name": "old-pkg", "version": "0.1.0",
                        "license": {"type": "MIT"}}),
            encoding="utf-8",
        )
        manifests = check_licenses.collect_npm_manifests(tmp_path)
        assert manifests[0]["license"] == "MIT"


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestSubprocessFailClosed:
    def test_pip_licenses_nonzero_exit_fails(self, monkeypatch, tmp_path):
        def fake_run(*a, **k):
            return _FakeCompleted(returncode=2, stderr="boom")
        monkeypatch.setattr(check_licenses.subprocess, "run", fake_run)
        code, violations, _ = check_licenses.check_python(tmp_path / "req.txt")
        assert code == 1
        assert any("pip-licenses-exit-2" in v for v in violations)

    def test_pip_licenses_unparsable_json_fails(self, monkeypatch, tmp_path):
        def fake_run(*a, **k):
            return _FakeCompleted(returncode=0, stdout="not-json{{{")
        monkeypatch.setattr(check_licenses.subprocess, "run", fake_run)
        code, violations, _ = check_licenses.check_python(tmp_path / "req.txt")
        assert code == 1
        assert any("unparsable-json" in v for v in violations)

    def test_pip_licenses_missing_binary_fails(self, monkeypatch, tmp_path):
        def fake_run(*a, **k):
            raise FileNotFoundError("no such program")
        monkeypatch.setattr(check_licenses.subprocess, "run", fake_run)
        code, violations, _ = check_licenses.check_python(tmp_path / "req.txt")
        assert code == 1
        assert any("pip-licenses-unavailable" in v for v in violations)
