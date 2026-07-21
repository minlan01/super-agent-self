"""Cache abstraction layer — pluggable backends with namespaced keys."""

from .base import CacheBackend
from .manager import CacheManager
from .memory import MemoryCacheBackend

try:
    from .redis import RedisCacheBackend
except ImportError:
    RedisCacheBackend = None  # redis package not installed

_cache: CacheManager | None = None


def get_cache() -> CacheManager:
    """Return the global :class:`CacheManager` singleton."""
    global _cache
    if _cache is None:
        _cache = CacheManager()
    return _cache


def reset_cache() -> None:
    """Reset the global singleton (useful in tests)."""
    global _cache
    _cache = None


__all__ = [
    "CacheBackend",
    "CacheManager",
    "MemoryCacheBackend",
    "RedisCacheBackend",
    "get_cache",
    "reset_cache",
]
