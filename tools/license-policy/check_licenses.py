#!/usr/bin/env python3
"""License policy check for Python + Node ecosystems (P4 blocker #9).

Exit 0 = all licenses approved; exit 1 = violations (CI gate fails).

Usage:
    python tools/license-policy/check_licenses.py \
        --requirements services/control-core/requirements-win-locked.txt \
        --npm-dir apps/desktop
"""

from __future__ import annotations

import argparse
import json
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
}

# Deny-by-default copyleft that requires legal review.
DENIED_PATTERNS = [
    re.compile(r"\bAGPL", re.I),
    re.compile(r"\bSSPL", re.I),
]


def check_python(requirements: Path) -> tuple[int, list[str]]:
    """pip-license check against the locked requirements file."""
    print(f"[python] checking {requirements}")
    result = subprocess.run(
        [sys.executable, "-m", "pip_license", "--from=requirements",
         f"--requirements={requirements}", "--format=json", "--with-authors=no"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"[python] pip-license failed:\n{result.stderr}")
        print("  (install with: pip install pip-license)")
        return 1, ["pip-license-unavailable"]

    violations: list[str] = []
    entries = json.loads(result.stdout or "[]")
    for entry in entries:
        name = entry.get("Name", "?")
        license_str = (entry.get("License") or "").strip()
        # Normalize multi-license strings (pip-license uses ';'-separated).
        parts = [p.strip() for p in license_str.split(";") if p.strip()]
        bad = [p for p in parts if p and p not in APPROVED]
        if any(pat.search(license_str) for pat in DENIED_PATTERNS):
            violations.append(f"{name}: {license_str} (copyleft-deny)")
        elif bad:
            violations.append(f"{name}: {'; '.join(bad)}")
    return (1 if violations else 0), violations


def check_npm(npm_dir: Path) -> tuple[int, list[str]]:
    """npm license check via the production dependency tree."""
    print(f"[npm] checking {npm_dir}")
    result = subprocess.run(
        ["npm", "ls", "--prod", "--json", "--all"],
        capture_output=True, text=True, cwd=npm_dir,
    )
    try:
        tree = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        print(f"[npm] npm ls failed:\n{result.stderr[:500]}")
        return 1, ["npm-ls-unavailable"]

    violations: list[str] = []
    seen: set[str] = set()

    def walk(deps: dict) -> None:
        for name, info in deps.items():
            lic = info.get("license") or ""
            key = f"{name}@{info.get('version', '?')}"
            if key in seen:
                continue
            seen.add(key)
            if any(pat.search(str(lic)) for pat in DENIED_PATTERNS):
                violations.append(f"{key}: {lic} (copyleft-deny)")
            elif lic and lic not in APPROVED:
                violations.append(f"{key}: {lic}")
            walk(info.get("dependencies", {}) or {})

    walk(tree.get("dependencies", {}) or {})
    return (1 if violations else 0), violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path,
                        default=REPO_ROOT / "services/control-core/requirements-win-locked.txt")
    parser.add_argument("--npm-dir", type=Path,
                        default=REPO_ROOT / "apps/desktop")
    args = parser.parse_args()

    exit_code = 0
    py_code, py_violations = check_python(args.requirements)
    npm_code, npm_violations = check_npm(args.npm_dir)

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
