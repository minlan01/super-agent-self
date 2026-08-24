#!/usr/bin/env python3
"""License policy check for Python + Node ecosystems (P4 blocker #9).

Exit 0 = all licenses approved; exit 1 = violations (CI gate fails).

Fail-closed contract (release gate GA-1.4):
  - a missing/unusable license tool is a FAILURE, not a skip
  - unparsable tool output is a FAILURE
  - zero scanned components is a FAILURE
  - an empty/missing license on any component is a FAILURE
  - unknown SPDX / non-approved identifiers are FAILUREs
  - AGPL / SSPL anywhere is a FAILURE

Usage (run with the control-core venv python so pip-licenses sees the
locked environment):
    python tools/license-policy/check_licenses.py \
        --requirements services/control-core/requirements-win-locked.txt \
        --npm-dir apps/desktop
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Must match tools/license-policy/deny.toml [licenses].allow.
APPROVED = {
    "MIT", "MIT License",
    "Apache-2.0", "Apache Software License", "Apache 2.0",
    "BSD-2-Clause", "BSD-3-Clause",
    "BSD", "BSD License", "The BSD License", "BSD-3-Clause License",
    "ISC", "ISC License",
    "Zlib", "zlib License",
    "0BSD",
    "MPL-2.0", "MPL 2.0", "Mozilla Public License 2.0 (MPL 2.0)",
    "Unlicense", "The Unlicense (Unlicense)",
    "CC0-1.0",
    "Python Software Foundation License", "PSF",
    "Public Domain",
    "SQLite",  # public domain
    "OpenGL",  # licenses the OpenGL name (public-domain-style)
    "SIL Open Font License 1.1", "OFL-1.1",  # fonts
    "MIT OR Apache-2.0", "MIT OR GPL-2.0-or-later",  # dual, permissive arm present
    "MIT OR Apache-2.0 OR BSD-1-Clause",  # web locks etc
    "Apache-2.0 OR BSD-2-Clause OR MIT",  # pytest deps style
    "MIT OR BSD-3-Clause OR Apache-2.0",
    "BSD-3-Clause OR MIT",
    "MIT AND (Apache-2.0 OR BSD-2-Clause)",
    "LGPL-2.1-or-later AND MIT AND Python-2.0",  # python-docx ecosystem (reviewed)
    "Python-2.0", "Python License",  # PSF-style
    "Apache-2.0 AND MIT",
    "MIT AND Apache-2.0",
    "BSD AND MIT",
    # ── Reviewed for v1.0.0 Personal/Internal GA (2026-08-23) ────────────
    # All entries below are permissive or dual-license with a permissive
    # arm; none is AGPL/SSPL. Personal/Internal use only — revisit before
    # any public distribution.
    "Apache-2.0 OR MIT",  # @tauri-apps/* (api, cli, cli-win32-x64-msvc)
    "MIT AND PSF-2.0",  # greenlet
    "PSF-2.0",  # typing_extensions
    "ISC License (ISCL)",  # isoduration, shellingham (== ISC)
    "MIT-CMU",  # pillow (MIT-style, CMU variant)
    "Apache-2.0 OR BSD-2-Clause",  # packaging
    "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",  # numpy (all permissive)
    "Artistic License; GNU General Public License (GPL); GNU General Public License v2 or later (GPLv2+)",  # text-unidecode (Artistic OR GPL dual; Artistic arm)
    "GNU Lesser General Public License v2 or later (LGPLv2+)",  # chardet (LGPL, dynamic dep of requests)
    "GNU Library or Lesser General Public License (LGPL)",  # psycopg2-binary (LGPL w/ FOSS exception)
}

# Distributions owned by this repository that appear in the local venv;
# their license is the repository's own decision, not a third-party input.
OWN_PACKAGES = {"controlled-agent-platform"}

# Deny-by-default copyleft that requires legal review.
DENIED_PATTERNS = [
    re.compile(r"\bAGPL", re.I),
    re.compile(r"\bSSPL", re.I),
]


def _license_violation(key: str, license_str: str) -> str | None:
    """Return a violation string for one component, or None if approved."""
    stripped = (license_str or "").strip()
    if any(pat.search(stripped) for pat in DENIED_PATTERNS):
        return f"{key}: {stripped} (copyleft-deny)"
    if not stripped:
        return f"{key}: <missing/empty license> (fail-closed)"
    if stripped in APPROVED:
        return None
    parts = [p.strip() for p in stripped.split(";") if p.strip()]
    bad = [p for p in parts if p and p not in APPROVED]
    if bad:
        return f"{key}: {'; '.join(bad)}"
    return None


def python_violations_from_entries(entries: list[dict]) -> tuple[int, list[str], int]:
    """Pure check over pip-licenses JSON entries. Zero entries => failure."""
    if not isinstance(entries, list) or not entries:
        return 1, ["python-zero-components (fail-closed)"], 0
    violations: list[str] = []
    count = 0
    for entry in entries:
        name = str(entry.get("Name", "?"))
        if name in OWN_PACKAGES:
            continue
        license_str = entry.get("License") or ""
        count += 1
        violation = _license_violation(name, str(license_str))
        if violation:
            violations.append(violation)
    if count == 0:
        return 1, ["python-zero-components (fail-closed)"], 0
    return (1 if violations else 0), violations, count


def npm_violations_from_manifests(manifests: list[dict]) -> tuple[int, list[str], int]:
    """Pure check over collected package.json manifests.

    ``npm ls --json`` output carries no license field at all — the only
    reliable source is each installed package's actual manifest
    (release gate GA-1.4). Zero manifests => failure.
    """
    if not manifests:
        return 1, ["npm-zero-components (fail-closed)"], 0
    violations: list[str] = []
    seen: set[str] = set()
    count = 0
    for m in manifests:
        key = f"{m.get('name', '?')}@{m.get('version', '?')}"
        if key in seen:
            continue
        seen.add(key)
        count += 1
        violation = _license_violation(key, str(m.get("license") or ""))
        if violation:
            violations.append(violation)
    return (1 if violations else 0), violations, count


def collect_npm_manifests(npm_dir: Path) -> list[dict]:
    """Read every installed package's real package.json under node_modules."""
    node_modules = npm_dir / "node_modules"
    if not node_modules.is_dir():
        return []
    manifests: list[dict] = []
    for manifest_path in node_modules.rglob("package.json"):
        if manifest_path.name != "package.json":
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifests.append({
                "name": str(manifest_path), "version": "?", "license": "",
            })
            continue
        if not isinstance(data, dict) or "name" not in data:
            continue
        license_field = data.get("license")
        if isinstance(license_field, dict):  # legacy object form
            license_field = license_field.get("type") or ""
        manifests.append({
            "name": data.get("name"),
            "version": data.get("version") or "?",
            "license": license_field or "",
        })
    return manifests


def _npm_command() -> str:
    """npm executable (kept for any future npm-CLI-based cross-checks)."""
    if os.name == "nt":
        return "npm.cmd"
    return "npm"


def check_python(requirements: Path) -> tuple[int, list[str], int]:
    """pip-licenses (module ``piplicenses``) against the current environment."""
    print(f"[python] checking environment for {requirements}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "piplicenses", "--format=json"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
    except FileNotFoundError:
        return 1, ["pip-licenses-unavailable (fail-closed; install with: "
                   "pip install pip-licenses==5.5.5)"], 0
    if result.returncode != 0:
        print(f"[python] pip-licenses failed:\n{result.stderr}")
        return 1, [f"pip-licenses-exit-{result.returncode} (fail-closed)"], 0

    try:
        entries = json.loads(result.stdout or "")
    except json.JSONDecodeError:
        print(f"[python] pip-licenses produced unparsable JSON:\n{result.stdout[:500]}")
        return 1, ["pip-licenses-unparsable-json (fail-closed)"], 0

    code, violations, count = python_violations_from_entries(entries)
    print(f"[python] components={count}")
    return code, violations, count


def check_npm(npm_dir: Path) -> tuple[int, list[str], int]:
    """npm license check via each installed package's actual manifest."""
    print(f"[npm] checking manifests under {npm_dir / 'node_modules'}")
    manifests = collect_npm_manifests(npm_dir)
    if not manifests:
        print("[npm] node_modules missing or empty — dependencies not installed")
        return 1, ["npm-not-installed (fail-closed; run npm ci)"], 0

    code, violations, count = npm_violations_from_manifests(manifests)
    print(f"[npm] components={count}")
    return code, violations, count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path,
                        default=REPO_ROOT / "services/control-core/requirements-win-locked.txt")
    parser.add_argument("--npm-dir", type=Path,
                        default=REPO_ROOT / "apps/desktop")
    args = parser.parse_args()

    exit_code = 0
    py_code, py_violations, py_count = check_python(args.requirements)
    npm_code, npm_violations, npm_count = check_npm(args.npm_dir)
    print(f"\n[summary] python_components={py_count} npm_components={npm_count} "
          f"violations={len(py_violations) + len(npm_violations)}")

    for v in py_violations + npm_violations:
        print(f"  VIOLATION: {v}")
    if py_violations or npm_violations:
        print(f"\nlicense policy FAILED: {len(py_violations) + len(npm_violations)} violation(s)")
        print("review and either add to APPROVED (with rationale) or remove the dependency")
        exit_code = 1
    else:
        print("\nlicense policy PASSED (python + npm)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
