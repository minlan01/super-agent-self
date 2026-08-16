"""Runtime selection for concrete platform adapters."""

from __future__ import annotations

import sys
from functools import lru_cache

from packages.platform.shared.contracts import PlatformAdapter, StubPlatformAdapter


@lru_cache(maxsize=1)
def get_platform_adapter() -> PlatformAdapter:
    if sys.platform == "win32":
        from packages.platform.windows.adapter import WindowsPlatformAdapter

        return WindowsPlatformAdapter()
    return StubPlatformAdapter()


def clear_platform_adapter_cache() -> None:
    get_platform_adapter.cache_clear()


__all__ = ["clear_platform_adapter_cache", "get_platform_adapter"]
