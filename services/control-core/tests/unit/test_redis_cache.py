"""Unit tests for packages/cache/redis.py — RedisCacheBackend + CacheManager factory."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# sys is used in TestRedisCacheBackendImport for module manipulation
import pytest

from packages.cache import (
    CacheBackend,
    CacheManager,
    MemoryCacheBackend,
    RedisCacheBackend,
    reset_cache,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


class MockRedis:
    """Minimal mock of redis.asyncio.Redis for unit testing.

    Stores values in a plain dict.  Supports get/set/delete/exists/scan_iter.
    """

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    async def delete(self, *keys: str):
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    def scan_iter(self, match: str = "*", count: int | None = None):
        import fnmatch

        async def _gen():
            for k in list(self._store.keys()):
                if fnmatch.fnmatch(k, match):
                    yield k

        return _gen()

    async def close(self):
        pass


@pytest.fixture()
def mock_redis() -> MockRedis:
    return MockRedis()


@pytest.fixture()
def redis_backend(mock_redis: MockRedis) -> RedisCacheBackend:
    """Create a RedisCacheBackend with a mocked redis client.

    Bypass __init__ to avoid the real import, then set attributes manually.
    """
    backend = RedisCacheBackend.__new__(RedisCacheBackend)
    backend._redis = mock_redis
    backend._prefix = "test:"
    backend._default_ttl = 300
    backend._healthy = True
    backend._last_fail_time = 0.0
    backend._redis_url = "redis://mock"
    return backend


@pytest.fixture(autouse=True)
def _reset_global_cache():
    reset_cache()
    yield
    reset_cache()


# ── RedisCacheBackend — basic CRUD ────────────────────────────────────────


class TestRedisCacheBackendBasic:
    """get / set / delete / exists basics with mocked redis."""

    @pytest.mark.asyncio
    async def test_get_miss(self, redis_backend: RedisCacheBackend):
        assert await redis_backend.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        await redis_backend.set("k1", "v1")
        assert await redis_backend.get("k1") == "v1"

    @pytest.mark.asyncio
    async def test_set_serializes_json(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        await redis_backend.set("k1", {"a": 1, "b": [2, 3]})
        # Raw redis value should be JSON
        raw = mock_redis._store.get("test:k1")
        assert raw is not None
        assert json.loads(raw) == {"a": 1, "b": [2, 3]}

    @pytest.mark.asyncio
    async def test_get_deserializes_json(self, redis_backend: RedisCacheBackend):
        await redis_backend.set("k1", [1, 2, 3])
        result = await redis_backend.get("k1")
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_get_returns_raw_on_non_json(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        """If the stored value is not valid JSON, return it as-is."""
        mock_redis._store["test:raw"] = "not-json"
        result = await redis_backend.get("raw")
        assert result == "not-json"

    @pytest.mark.asyncio
    async def test_overwrite(self, redis_backend: RedisCacheBackend):
        await redis_backend.set("k1", "v1")
        await redis_backend.set("k1", "v2")
        assert await redis_backend.get("k1") == "v2"

    @pytest.mark.asyncio
    async def test_delete(self, redis_backend: RedisCacheBackend):
        await redis_backend.set("k1", "v1")
        await redis_backend.delete("k1")
        assert await redis_backend.get("k1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, redis_backend: RedisCacheBackend):
        await redis_backend.delete("does_not_exist")  # should not raise

    @pytest.mark.asyncio
    async def test_exists_hit(self, redis_backend: RedisCacheBackend):
        await redis_backend.set("k1", "v1")
        assert await redis_backend.exists("k1") is True

    @pytest.mark.asyncio
    async def test_exists_miss(self, redis_backend: RedisCacheBackend):
        assert await redis_backend.exists("nope") is False


# ── RedisCacheBackend — prefix handling ───────────────────────────────────


class TestRedisCacheBackendPrefix:
    """Key prefixing behaviour."""

    @pytest.mark.asyncio
    async def test_prefix_applied_on_set(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        await redis_backend.set("mykey", "val")
        assert "test:mykey" in mock_redis._store
        assert "mykey" not in mock_redis._store

    @pytest.mark.asyncio
    async def test_prefix_applied_on_get(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        mock_redis._store["test:mykey"] = json.dumps("val")
        result = await redis_backend.get("mykey")
        assert result == "val"

    @pytest.mark.asyncio
    async def test_prefix_applied_on_delete(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        mock_redis._store["test:mykey"] = json.dumps("val")
        await redis_backend.delete("mykey")
        assert "test:mykey" not in mock_redis._store

    @pytest.mark.asyncio
    async def test_prefix_applied_on_exists(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        mock_redis._store["test:mykey"] = json.dumps("val")
        assert await redis_backend.exists("mykey") is True
        assert await redis_backend.exists("wrong:mykey") is False


# ── RedisCacheBackend — TTL ───────────────────────────────────────────────


class TestRedisCacheBackendTTL:
    """TTL is passed as the `ex` parameter to redis SET."""

    @pytest.mark.asyncio
    async def test_default_ttl_used(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        """Default TTL (300) should be passed as `ex` param."""
        mock_redis.set = AsyncMock()
        mock_redis.set.side_effect = lambda k, v, ex=None: None
        await redis_backend.set("k1", "v1")
        mock_redis.set.assert_called_once_with("test:k1", json.dumps("v1"), ex=300)

    @pytest.mark.asyncio
    async def test_custom_ttl_overrides_default(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        mock_redis.set = AsyncMock()
        mock_redis.set.side_effect = lambda k, v, ex=None: None
        await redis_backend.set("k1", "v1", ttl=60)
        mock_redis.set.assert_called_once_with("test:k1", json.dumps("v1"), ex=60)


# ── RedisCacheBackend — clear with scan_iter ──────────────────────────────


class TestRedisCacheBackendClear:
    """Pattern-based clearing using scan_iter."""

    @pytest.mark.asyncio
    async def test_clear_all(self, redis_backend: RedisCacheBackend):
        for i in range(3):
            await redis_backend.set(f"k{i}", i)
        count = await redis_backend.clear("*")
        assert count == 3
        assert await redis_backend.get("k0") is None

    @pytest.mark.asyncio
    async def test_clear_pattern(self, redis_backend: RedisCacheBackend):
        await redis_backend.set("task:1", "a")
        await redis_backend.set("task:2", "b")
        await redis_backend.set("skill:1", "c")
        count = await redis_backend.clear("task:*")
        assert count == 2
        assert await redis_backend.get("task:1") is None
        assert await redis_backend.get("skill:1") == "c"

    @pytest.mark.asyncio
    async def test_clear_returns_zero_on_empty(self, redis_backend: RedisCacheBackend):
        count = await redis_backend.clear("*")
        assert count == 0


# ── RedisCacheBackend — close ─────────────────────────────────────────────


class TestRedisCacheBackendClose:
    """The close method delegates to redis.close()."""

    @pytest.mark.asyncio
    async def test_close_delegates(self, redis_backend: RedisCacheBackend, mock_redis: MockRedis):
        mock_redis.close = AsyncMock()
        await redis_backend.close()
        mock_redis.close.assert_called_once()


# ── RedisCacheBackend — ImportError when redis not installed ──────────────


class TestRedisCacheBackendImport:
    """RedisCacheBackend raises ImportError if redis package is missing."""

    def test_import_error_without_redis(self):
        """Instantiating RedisCacheBackend when redis is not installed raises ImportError."""
        # Save the real redis module state
        real_redis = sys.modules.get("redis")
        real_redis_asyncio = sys.modules.get("redis.asyncio")

        try:
            # Remove redis modules to simulate them not being installed
            sys.modules["redis"] = None
            sys.modules["redis.asyncio"] = None

            with pytest.raises(ImportError, match="redis package is required"):
                RedisCacheBackend.__new__(RedisCacheBackend).__init__(
                    redis_url="redis://localhost:6379/0"
                )
        finally:
            # Restore
            if real_redis is not None:
                sys.modules["redis"] = real_redis
            else:
                sys.modules.pop("redis", None)
            if real_redis_asyncio is not None:
                sys.modules["redis.asyncio"] = real_redis_asyncio
            else:
                sys.modules.pop("redis.asyncio", None)


# ── RedisCacheBackend — is a CacheBackend ─────────────────────────────────


class TestRedisCacheBackendABC:
    """Verify RedisCacheBackend is a proper CacheBackend."""

    def test_is_subclass(self):
        assert issubclass(RedisCacheBackend, CacheBackend)


# ── CacheManager — backend factory ────────────────────────────────────────


class TestCacheManagerFactory:
    """CacheManager._create_backend_from_config creates the right backend."""

    @pytest.mark.asyncio
    async def test_factory_creates_memory_by_default(self):
        """When backend is not specified, MemoryCacheBackend is created."""
        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"max_size": 50, "default_ttl": 60}},
        ):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_factory_creates_memory_explicitly(self):
        """When backend=memory, MemoryCacheBackend is created."""
        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"backend": "memory"}},
        ):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_factory_creates_redis_when_configured(self):
        """When backend=redis in config and redis is importable, RedisCacheBackend is created."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"backend": "redis", "redis_url": "redis://localhost:6379/1"}},
        ), patch("redis.asyncio.from_url", return_value=mock_client):
            mgr = CacheManager()
            assert isinstance(mgr._backend, RedisCacheBackend)

    @pytest.mark.asyncio
    async def test_factory_falls_back_when_redis_import_fails(self):
        """When backend=redis but redis package is not installed, fall back to memory."""
        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"backend": "redis"}},
        ), patch("redis.asyncio.from_url", side_effect=ImportError("no redis")):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_factory_falls_back_when_redis_connection_fails(self):
        """When backend=redis but connection fails, fall back to memory."""
        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"backend": "redis", "redis_url": "redis://bad:6379/0"}},
        ), patch("redis.asyncio.from_url", side_effect=Exception("connection refused")):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_factory_uses_custom_redis_url(self):
        """Redis URL from config is passed to RedisCacheBackend."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"backend": "redis", "redis_url": "redis://custom:6380/2"}},
        ), patch("redis.asyncio.from_url", return_value=mock_client) as mock_from_url:
            mgr = CacheManager()
            assert isinstance(mgr._backend, RedisCacheBackend)
            mock_from_url.assert_called_once_with(
                "redis://custom:6380/2", decode_responses=True
            )

    @pytest.mark.asyncio
    async def test_factory_uses_custom_ttl(self):
        """default_ttl from config is passed to the backend."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with patch(
            "packages.cache.manager._load_cache_config",
            return_value={"cache": {"backend": "redis", "default_ttl": 600}},
        ), patch("redis.asyncio.from_url", return_value=mock_client):
            mgr = CacheManager()
            assert isinstance(mgr._backend, RedisCacheBackend)
            assert mgr._backend._default_ttl == 600

    @pytest.mark.asyncio
    async def test_factory_empty_config_defaults_to_memory(self):
        """Empty config (no cache key) defaults to MemoryCacheBackend."""
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)
            assert mgr._backend.max_size == 1000
            assert mgr._backend.default_ttl == 300
