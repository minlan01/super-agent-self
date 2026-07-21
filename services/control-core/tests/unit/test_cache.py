"""Unit tests for packages/cache — MemoryCacheBackend + CacheManager."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

import pytest

from packages.cache import (
    CacheBackend,
    CacheManager,
    MemoryCacheBackend,
    get_cache,
    reset_cache,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def backend() -> MemoryCacheBackend:
    """Fresh MemoryCacheBackend for each test."""
    return MemoryCacheBackend(max_size=5, default_ttl=10.0)


@pytest.fixture(autouse=True)
def _reset_global_cache():
    """Ensure the global singleton never leaks between tests."""
    reset_cache()
    yield
    reset_cache()


# ── MemoryCacheBackend — basic CRUD ──────────────────────────────────────


class TestMemoryCacheBackendBasic:
    """get / set / delete / exists / clear basics."""

    @pytest.mark.asyncio
    async def test_get_miss(self, backend: MemoryCacheBackend):
        assert await backend.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, backend: MemoryCacheBackend):
        await backend.set("k1", "v1")
        assert await backend.get("k1") == "v1"

    @pytest.mark.asyncio
    async def test_overwrite(self, backend: MemoryCacheBackend):
        await backend.set("k1", "v1")
        await backend.set("k1", "v2")
        assert await backend.get("k1") == "v2"

    @pytest.mark.asyncio
    async def test_delete(self, backend: MemoryCacheBackend):
        await backend.set("k1", "v1")
        await backend.delete("k1")
        assert await backend.get("k1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, backend: MemoryCacheBackend):
        await backend.delete("does_not_exist")  # should not raise

    @pytest.mark.asyncio
    async def test_exists_hit(self, backend: MemoryCacheBackend):
        await backend.set("k1", "v1")
        assert await backend.exists("k1") is True

    @pytest.mark.asyncio
    async def test_exists_miss(self, backend: MemoryCacheBackend):
        assert await backend.exists("nope") is False

    @pytest.mark.asyncio
    async def test_clear_all(self, backend: MemoryCacheBackend):
        for i in range(3):
            await backend.set(f"k{i}", i)
        count = await backend.clear("*")
        assert count == 3
        assert await backend.get("k0") is None

    @pytest.mark.asyncio
    async def test_clear_pattern(self, backend: MemoryCacheBackend):
        await backend.set("task:1", "a")
        await backend.set("task:2", "b")
        await backend.set("skill:1", "c")
        count = await backend.clear("task:*")
        assert count == 2
        assert await backend.get("task:1") is None
        assert await backend.get("skill:1") == "c"

    @pytest.mark.asyncio
    async def test_clear_returns_zero_on_empty(self, backend: MemoryCacheBackend):
        count = await backend.clear("*")
        assert count == 0


# ── MemoryCacheBackend — TTL expiration ──────────────────────────────────


class TestMemoryCacheBackendTTL:
    """Time-to-live expiration behaviour."""

    @pytest.mark.asyncio
    async def test_ttl_expires_get(self, backend: MemoryCacheBackend):
        await backend.set("k1", "v1", ttl=0.05)
        assert await backend.get("k1") == "v1"
        await asyncio.sleep(0.1)
        assert await backend.get("k1") is None

    @pytest.mark.asyncio
    async def test_ttl_expires_exists(self, backend: MemoryCacheBackend):
        await backend.set("k1", "v1", ttl=0.05)
        assert await backend.exists("k1") is True
        await asyncio.sleep(0.1)
        assert await backend.exists("k1") is False

    @pytest.mark.asyncio
    async def test_ttl_expires_cleared(self, backend: MemoryCacheBackend):
        """Expired entries should be cleaned up on clear."""
        await backend.set("k1", "v1", ttl=0.05)
        await asyncio.sleep(0.1)
        count = await backend.clear("*")
        assert count == 0

    @pytest.mark.asyncio
    async def test_default_ttl_used_when_none(self):
        b = MemoryCacheBackend(max_size=10, default_ttl=0.05)
        await b.set("k1", "v1")  # uses default_ttl
        await asyncio.sleep(0.1)
        assert await b.get("k1") is None


# ── MemoryCacheBackend — LRU eviction ────────────────────────────────────


class TestMemoryCacheBackendLRU:
    """Least-recently-used eviction when max_size is exceeded."""

    @pytest.mark.asyncio
    async def test_lru_eviction_on_set(self, backend: MemoryCacheBackend):
        """backend has max_size=5; inserting a 6th key evicts the oldest."""
        for i in range(5):
            await backend.set(f"k{i}", i)
        # All 5 present
        assert await backend.exists("k0")
        # Insert 6th — evicts k0
        await backend.set("k5", 5)
        assert await backend.get("k0") is None
        assert await backend.get("k5") == 5

    @pytest.mark.asyncio
    async def test_lru_access_refreshes(self, backend: MemoryCacheBackend):
        """Accessing a key should move it to the end (most recently used)."""
        for i in range(5):
            await backend.set(f"k{i}", i)
        # Touch k0 — refreshes its position
        await backend.get("k0")
        # Insert 6th — should evict k1 (now oldest), not k0
        await backend.set("k5", 5)
        assert await backend.get("k0") == 0  # still present
        assert await backend.get("k1") is None  # evicted


# ── MemoryCacheBackend — thread safety ───────────────────────────────────


class TestMemoryCacheBackendThreadSafety:
    """Concurrent access from multiple threads."""

    @pytest.mark.asyncio
    async def test_concurrent_writes(self):
        b = MemoryCacheBackend(max_size=500, default_ttl=60)
        errors: list[Exception] = []

        async def writer(idx: int):
            try:
                for j in range(50):
                    await b.set(f"t{idx}:k{j}", idx * 100 + j)
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(*(writer(i) for i in range(10)))
        assert errors == []
        # At least some keys should survive
        count = 0
        for i in range(10):
            for j in range(50):
                if await b.get(f"t{i}:k{j}") is not None:
                    count += 1
        assert count > 0

    def test_sync_concurrent_writes(self):
        """Thread-safety via threading.Lock — synchronous wrapper."""
        b = MemoryCacheBackend(max_size=500, default_ttl=60)
        errors: list[Exception] = []

        def writer(idx: int):
            loop = asyncio.new_event_loop()
            try:
                for j in range(50):
                    loop.run_until_complete(b.set(f"t{idx}:k{j}", idx * 100 + j))
            except Exception as exc:
                errors.append(exc)
            finally:
                loop.close()

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ── MemoryCacheBackend — values of various types ─────────────────────────


class TestMemoryCacheBackendValueTypes:
    """Ensure arbitrary Python objects can be cached."""

    @pytest.mark.asyncio
    async def test_cache_dict(self, backend: MemoryCacheBackend):
        data = {"tasks": [1, 2, 3], "count": 3}
        await backend.set("d1", data)
        assert await backend.get("d1") == data

    @pytest.mark.asyncio
    async def test_cache_none_value(self, backend: MemoryCacheBackend):
        await backend.set("n1", None)
        # get returns None for both miss and cached-None;
        # exists distinguishes them
        assert await backend.exists("n1") is True

    @pytest.mark.asyncio
    async def test_cache_list(self, backend: MemoryCacheBackend):
        await backend.set("l1", [1, "two", 3.0])
        assert await backend.get("l1") == [1, "two", 3.0]


# ── CacheManager — namespaced operations ─────────────────────────────────


class TestCacheManager:
    """High-level CacheManager with namespaces and invalidation."""

    @pytest.mark.asyncio
    async def test_namespaced_set_get(self):
        mgr = CacheManager(prefix="test")
        await mgr.set("tasks", "abc", {"goal": "do stuff"})
        assert await mgr.get("tasks", "abc") == {"goal": "do stuff"}

    @pytest.mark.asyncio
    async def test_namespaced_isolation(self):
        mgr = CacheManager(prefix="test")
        await mgr.set("tasks", "key1", "task-value")
        await mgr.set("skills", "key1", "skill-value")
        assert await mgr.get("tasks", "key1") == "task-value"
        assert await mgr.get("skills", "key1") == "skill-value"

    @pytest.mark.asyncio
    async def test_invalidate_namespace(self):
        mgr = CacheManager(prefix="test")
        await mgr.set("tasks", "k1", "v1")
        await mgr.set("tasks", "k2", "v2")
        await mgr.set("skills", "k1", "v1")
        count = await mgr.invalidate("tasks")
        assert count == 2
        assert await mgr.get("tasks", "k1") is None
        assert await mgr.get("skills", "k1") == "v1"

    @pytest.mark.asyncio
    async def test_convenience_tasks(self):
        mgr = CacheManager(prefix="test")
        qh = mgr.hash_query({"status": "running", "limit": 20})
        await mgr.set_tasks(qh, [{"id": "t1"}])
        assert await mgr.get_tasks(qh) == [{"id": "t1"}]

    @pytest.mark.asyncio
    async def test_convenience_dashboard(self):
        mgr = CacheManager(prefix="test")
        stats = {"total_tasks": 42}
        await mgr.set_dashboard(stats)
        assert await mgr.get_dashboard() == stats

    @pytest.mark.asyncio
    async def test_convenience_invalidate_tasks(self):
        mgr = CacheManager(prefix="test")
        await mgr.set_tasks("h1", "v1")
        count = await mgr.invalidate_tasks()
        assert count == 1
        assert await mgr.get_tasks("h1") is None

    @pytest.mark.asyncio
    async def test_convenience_invalidate_dashboard(self):
        mgr = CacheManager(prefix="test")
        await mgr.set_dashboard({"x": 1})
        count = await mgr.invalidate_dashboard()
        assert count == 1
        assert await mgr.get_dashboard() is None

    @pytest.mark.asyncio
    async def test_hash_query_deterministic(self):
        h1 = CacheManager.hash_query({"a": 1, "b": 2})
        h2 = CacheManager.hash_query({"b": 2, "a": 1})
        assert h1 == h2

    @pytest.mark.asyncio
    async def test_hash_query_different_params(self):
        h1 = CacheManager.hash_query({"a": 1})
        h2 = CacheManager.hash_query({"a": 2})
        assert h1 != h2

    @pytest.mark.asyncio
    async def test_custom_backend(self):
        """CacheManager accepts an externally-created backend."""
        mem = MemoryCacheBackend(max_size=10, default_ttl=60)
        mgr = CacheManager(backend=mem, prefix="custom")
        await mgr.set("ns", "k", "v")
        # Directly on the backend the key is namespaced
        assert await mem.get("custom:ns:k") == "v"


# ── Global singleton ─────────────────────────────────────────────────────


class TestGlobalCache:
    """get_cache / reset_cache singleton behaviour."""

    @pytest.mark.asyncio
    async def test_get_cache_returns_manager(self):
        cache = get_cache()
        assert isinstance(cache, CacheManager)

    @pytest.mark.asyncio
    async def test_get_cache_singleton(self):
        assert get_cache() is get_cache()

    @pytest.mark.asyncio
    async def test_reset_cache_clears_singleton(self):
        first = get_cache()
        reset_cache()
        second = get_cache()
        assert first is not second

    @pytest.mark.asyncio
    async def test_global_cache_set_get(self):
        cache = get_cache()
        await cache.set_tasks("h1", {"goal": "test"})
        assert await cache.get_tasks("h1") == {"goal": "test"}


# ── CacheManager — config loading ────────────────────────────────────────


class TestCacheManagerConfig:
    """Verify YAML config is respected when present."""

    @pytest.mark.asyncio
    async def test_config_namespace_ttl(self):
        """When configs/cache.yaml exists, namespace TTLs should be picked up."""
        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={
                "cache": {
                    "max_size": 50,
                    "default_ttl": 999,
                    "namespaces": {
                        "tasks": {"ttl": 0.05},
                    },
                }
            },
        ):
            mgr = CacheManager()
            assert mgr._backend.default_ttl == 999
            # tasks namespace TTL is 0.05s
            await mgr.set("tasks", "k1", "v1")
            await asyncio.sleep(0.1)
            assert await mgr.get("tasks", "k1") is None

    @pytest.mark.asyncio
    async def test_config_defaults_when_no_yaml(self):
        """When no config file exists, defaults should be used."""
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager()
            assert mgr._backend.max_size == 1000
            assert mgr._backend.default_ttl == 300


# ── CacheBackend abstract contract ───────────────────────────────────────


class TestCacheBackendABC:
    """Verify CacheBackend cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            CacheBackend()  # type: ignore[abstract]

    def test_memory_is_subclass(self):
        assert issubclass(MemoryCacheBackend, CacheBackend)
