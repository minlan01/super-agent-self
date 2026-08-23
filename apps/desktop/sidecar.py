"""Compatibility entry point for local desktop development.

The packaged sidecar entry point is
``services/control-core/scripts/nuitka-build/control_core_sidecar.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "services" / "control-core"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.platform.windows.sidecar_host import main  # noqa: E402


if __name__ == "__main__":
    main()
