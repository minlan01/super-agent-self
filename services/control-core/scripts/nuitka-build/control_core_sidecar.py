"""Nuitka entry point for the real control-core Windows sidecar."""

from __future__ import annotations

import sys
from pathlib import Path


def _control_core_root() -> Path:
    # Source checkout: scripts/nuitka-build/<entry> -> control-core.
    # Standalone builds use the executable directory and already contain the
    # packages tree, so the sidecar module can discover that root itself.
    return Path(__file__).resolve().parents[2]


root = _control_core_root()
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from packages.platform.windows.sidecar_host import main  # noqa: E402


if __name__ == "__main__":
    main()
