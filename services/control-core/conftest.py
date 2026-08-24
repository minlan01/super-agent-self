"""Repo-root pytest conftest — applies to every collection under services/control-core.

Why this exists (2026-08-23, release gate GA-3):
  * The default ``pytest-of-USER`` temp scheme creates a ``pytest-current``
    junction on Windows, which requires a privilege this host lacks
    (WinError 1314), and stale runs have left both that tree and the
    project-local ``.pytest_tmp`` with deny-ACLs (WinError 5).
  * Solution: probe a project-local temp dir per session; if it (or its
    stale predecessor) is unusable, fall back to a per-process directory
    under the system temp.
Placed at this level (not tests/conftest.py) so ``pytest packages/...``
runs get the same treatment.
"""

from __future__ import annotations

import os
import pathlib


def pytest_configure(config):
    basetemp = pathlib.Path(__file__).resolve().parent / ".pytest_tmp"
    try:
        probe = basetemp / f".probe-{os.getpid()}"
        probe.mkdir(parents=True, exist_ok=True)
        probe.rmdir()
    except OSError:
        import tempfile

        fallback = pathlib.Path(tempfile.gettempdir()) / f"zcode-pytest-{os.getpid()}"
        fallback.mkdir(parents=True, exist_ok=True)
        basetemp = fallback
    config.option.basetemp = str(basetemp)
