"""Integration tests for the Redis cache layer.

Covers RedisCacheBackend (mocked redis.asyncio), CacheManager factory logic,
YAML config parsing, and namespaced operations through the manager when backed
by a (mocked) Redis instance.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.cache import CacheManager, MemoryCacheBackend, reset_cache
from packages.cache.redis import RedisCacheBackend

# ── Helpers ───────────────────────────────────────────────────────────────


def _async_iter(items: list):
    """Return an async iterator over *items*."""
    return _AsyncIterHelper(items)


class _AsyncIterHelper:
    """Minimal async iterator for use as scan_iter return value."""

    def __init__(self, items: list):
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


def _make_mock_redis():
    """Build a mocked redis.asyncio client with all methods used by RedisCacheBackend.

    ``scan_iter`` is a synchronous method that returns an async iterator, so we
    use a regular ``MagicMock`` (not ``AsyncMock``) for it to avoid wrapping the
    return value in a coroutine.
    """
    mock_redis = AsyncMock()
    # scan_iter is a sync method returning an async iterator — must NOT be AsyncMock
    mock_redis.scan_iter = MagicMock(return_value=_async_iter([]))
    return mock_redis


def _build_redis_backend(mock_redis, prefix="myagent:", default_ttl=300):
    """Construct a RedisCacheBackend bypassing __init__ and injecting a mock redis client.

    CacheManager already produces namespaced keys like ``prefix:ns:key``, so when
    a RedisCacheBackend is owned by CacheManager its own prefix should be the empty
    string to avoid double-prefixing.  For standalone backend tests the prefix
    (e.g. ``myagent:``) is kept.
    """
    backend = object.__new__(RedisCacheBackend)
    backend._prefix = prefix  # noqa: SLF001
    backend._default_ttl = default_ttl  # noqa: SLF001
    backend._redis = mock_redis
    backend._healthy = True  # noqa: SLF001
    backend._last_fail_time = 0.0  # noqa: SLF001
    return backend


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_global_cache():
    """Ensure the global singleton never leaks between tests."""
    reset_cache()
    yield
    reset_cache()


@pytest.fixture()
def mock_redis():
    """Provide a fresh mocked redis client."""
    return _make_mock_redis()


@pytest.fixture()
def redis_backend(mock_redis) -> RedisCacheBackend:
    """RedisCacheBackend with prefix ``myagent:`` for standalone backend tests."""
    return _build_redis_backend(mock_redis, prefix="myagent:")


# ── RedisCacheBackend — get / set with JSON serialization ────────────────


class TestRedisCacheBackendGetSet:
    """Verify get/set serialize and deserialize values via JSON."""

    @pytest.mark.asyncio
    async def test_set_dict(self, redis_backend, mock_redis):
        data = {"tasks": [1, 2, 3], "count": 3}
        await redis_backend.set("key1", data)
        mock_redis.set.assert_awaited_once_with(
            "myagent:key1", json.dumps(data), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_dict(self, redis_backend, mock_redis):
        data = {"name": "agent", "version": 3}
        mock_redis.get.return_value = json.dumps(data)
        result = await redis_backend.get("key1")
        assert result == data
        mock_redis.get.assert_awaited_once_with("myagent:key1")

    @pytest.mark.asyncio
    async def test_set_list(self, redis_backend, mock_redis):
        data = [1, "two", 3.0, None, True]
        await redis_backend.set("key1", data)
        mock_redis.set.assert_awaited_once_with(
            "myagent:key1", json.dumps(data), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_list(self, redis_backend, mock_redis):
        data = [1, "two", 3.0]
        mock_redis.get.return_value = json.dumps(data)
        result = await redis_backend.get("key1")
        assert result == data

    @pytest.mark.asyncio
    async def test_set_string(self, redis_backend, mock_redis):
        await redis_backend.set("key1", "hello")
        mock_redis.set.assert_awaited_once_with(
            "myagent:key1", json.dumps("hello"), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_string(self, redis_backend, mock_redis):
        mock_redis.get.return_value = json.dumps("hello")
        result = await redis_backend.get("key1")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_set_int(self, redis_backend, mock_redis):
        await redis_backend.set("key1", 42)
        mock_redis.set.assert_awaited_once_with(
            "myagent:key1", json.dumps(42), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_int(self, redis_backend, mock_redis):
        mock_redis.get.return_value = json.dumps(42)
        result = await redis_backend.get("key1")
        assert result == 42

    @pytest.mark.asyncio
    async def test_set_none(self, redis_backend, mock_redis):
        await redis_backend.set("key1", None)
        mock_redis.set.assert_awaited_once_with(
            "myagent:key1", json.dumps(None), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_none_value(self, redis_backend, mock_redis):
        """Redis returns the JSON string 'null'; get deserializes to None."""
        mock_redis.get.return_value = json.dumps(None)
        result = await redis_backend.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_miss(self, redis_backend, mock_redis):
        """Redis returns None (key not found) — get returns None."""
        mock_redis.get.return_value = None
        result = await redis_backend.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_non_json_fallback(self, redis_backend, mock_redis):
        """If Redis returns a plain string that is not valid JSON, return it as-is."""
        mock_redis.get.return_value = "plain-text-not-json-object"
        result = await redis_backend.get("key1")
        assert result == "plain-text-not-json-object"

    @pytest.mark.asyncio
    async def test_set_boolean(self, redis_backend, mock_redis):
        await redis_backend.set("flag", True)
        mock_redis.set.assert_awaited_once_with(
            "myagent:flag", json.dumps(True), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_boolean(self, redis_backend, mock_redis):
        mock_redis.get.return_value = json.dumps(True)
        assert await redis_backend.get("flag") is True

    @pytest.mark.asyncio
    async def test_set_nested_structure(self, redis_backend, mock_redis):
        data = {"a": {"b": [1, 2, {"c": 3}]}}
        await redis_backend.set("nested", data)
        mock_redis.set.assert_awaited_once_with(
            "myagent:nested", json.dumps(data), ex=300
        )

    @pytest.mark.asyncio
    async def test_get_nested_structure(self, redis_backend, mock_redis):
        data = {"a": {"b": [1, 2, {"c": 3}]}}
        mock_redis.get.return_value = json.dumps(data)
        assert await redis_backend.get("nested") == data


# ── RedisCacheBackend — TTL handling ─────────────────────────────────────


class TestRedisCacheBackendTTL:
    """Verify TTL is correctly passed to redis.set via the ex parameter."""

    @pytest.mark.asyncio
    async def test_default_ttl(self, redis_backend, mock_redis):
        await redis_backend.set("k", "v")
        mock_redis.set.assert_awaited_once_with(
            "myagent:k", json.dumps("v"), ex=300
        )

    @pytest.mark.asyncio
    async def test_custom_ttl(self, redis_backend, mock_redis):
        await redis_backend.set("k", "v", ttl=60)
        mock_redis.set.assert_awaited_once_with(
            "myagent:k", json.dumps("v"), ex=60
        )

    @pytest.mark.asyncio
    async def test_ttl_zero(self, redis_backend, mock_redis):
        await redis_backend.set("k", "v", ttl=0)
        mock_redis.set.assert_awaited_once_with(
            "myagent:k", json.dumps("v"), ex=0
        )

    @pytest.mark.asyncio
    async def test_ttl_float_truncated_to_int(self, redis_backend, mock_redis):
        """Redis ex parameter is integer — float TTL should be truncated."""
        await redis_backend.set("k", "v", ttl=99.7)
        mock_redis.set.assert_awaited_once_with(
            "myagent:k", json.dumps("v"), ex=int(99.7)
        )

    @pytest.mark.asyncio
    async def test_backend_with_custom_default_ttl(self, mock_redis):
        """RedisCacheBackend created with a non-default TTL."""
        backend = _build_redis_backend(mock_redis, prefix="test:", default_ttl=600)
        await backend.set("k", "v")
        mock_redis.set.assert_awaited_once_with(
            "test:k", json.dumps("v"), ex=600
        )


# ── RedisCacheBackend — delete ───────────────────────────────────────────


class TestRedisCacheBackendDelete:
    """Verify delete calls redis.delete with the prefixed key."""

    @pytest.mark.asyncio
    async def test_delete_calls_prefixed(self, redis_backend, mock_redis):
        await redis_backend.delete("mykey")
        mock_redis.delete.assert_awaited_once_with("myagent:mykey")

    @pytest.mark.asyncio
    async def test_delete_custom_prefix(self, mock_redis):
        backend = _build_redis_backend(mock_redis, prefix="custom:")
        await backend.delete("mykey")
        mock_redis.delete.assert_awaited_once_with("custom:mykey")


# ── RedisCacheBackend — clear with scan_iter ─────────────────────────────


class TestRedisCacheBackendClear:
    """Verify clear uses scan_iter pattern matching and deletes each key."""

    @pytest.mark.asyncio
    async def test_clear_all_wildcard(self, redis_backend, mock_redis):
        keys = ["myagent:k1", "myagent:k2", "myagent:k3"]
        mock_redis.scan_iter.return_value = _async_iter(keys)
        count = await redis_backend.clear("*")
        assert count == 3
        _args, kwargs = mock_redis.scan_iter.call_args
        assert kwargs.get("match") == "myagent:*"
        # clear() may batch deletes into a single call — assert key coverage.
        deleted_keys = set()
        for call in mock_redis.delete.await_args_list:
            deleted_keys.update(a for a in call.args if isinstance(a, (str, list)))
        flattened = {k for item in deleted_keys for k in (item if isinstance(item, list) else [item])}
        assert set(keys) <= flattened

    @pytest.mark.asyncio
    async def test_clear_specific_pattern(self, redis_backend, mock_redis):
        keys = ["myagent:task:1", "myagent:task:2"]
        mock_redis.scan_iter.return_value = _async_iter(keys)
        count = await redis_backend.clear("task:*")
        assert count == 2
        _args, kwargs = mock_redis.scan_iter.call_args
        assert kwargs.get("match") == "myagent:task:*"

    @pytest.mark.asyncio
    async def test_clear_empty(self, redis_backend, mock_redis):
        """No matching keys — returns 0, no deletes."""
        mock_redis.scan_iter.return_value = _async_iter([])
        count = await redis_backend.clear("*")
        assert count == 0
        mock_redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clear_single_key(self, redis_backend, mock_redis):
        mock_redis.scan_iter.return_value = _async_iter(["myagent:solo"])
        count = await redis_backend.clear("solo")
        assert count == 1
        mock_redis.delete.assert_awaited_once_with("myagent:solo")


# ── RedisCacheBackend — exists ───────────────────────────────────────────


class TestRedisCacheBackendExists:
    """Verify exists checks the prefixed key and returns a boolean."""

    @pytest.mark.asyncio
    async def test_exists_true(self, redis_backend, mock_redis):
        mock_redis.exists.return_value = 1
        assert await redis_backend.exists("k") is True
        mock_redis.exists.assert_awaited_once_with("myagent:k")

    @pytest.mark.asyncio
    async def test_exists_false(self, redis_backend, mock_redis):
        mock_redis.exists.return_value = 0
        assert await redis_backend.exists("k") is False

    @pytest.mark.asyncio
    async def test_exists_returns_truish(self, redis_backend, mock_redis):
        """Redis EXISTS returns the count of matching keys — bool() coercion."""
        mock_redis.exists.return_value = 3
        assert await redis_backend.exists("k") is True


# ── RedisCacheBackend — close ────────────────────────────────────────────


class TestRedisCacheBackendClose:
    """Verify close delegates to redis.close()."""

    @pytest.mark.asyncio
    async def test_close(self, redis_backend, mock_redis):
        await redis_backend.close()
        mock_redis.close.assert_awaited_once()


# ── RedisCacheBackend — prefix application ───────────────────────────────


class TestRedisCacheBackendPrefix:
    """Verify all operations apply the configured prefix."""

    @pytest.mark.asyncio
    async def test_prefix_on_get(self, redis_backend, mock_redis):
        mock_redis.get.return_value = None
        await redis_backend.get("x")
        mock_redis.get.assert_awaited_once_with("myagent:x")

    @pytest.mark.asyncio
    async def test_prefix_on_set(self, redis_backend, mock_redis):
        await redis_backend.set("x", 1)
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "myagent:x"

    @pytest.mark.asyncio
    async def test_prefix_on_delete(self, redis_backend, mock_redis):
        await redis_backend.delete("x")
        mock_redis.delete.assert_awaited_once_with("myagent:x")

    @pytest.mark.asyncio
    async def test_prefix_on_exists(self, redis_backend, mock_redis):
        mock_redis.exists.return_value = 0
        await redis_backend.exists("x")
        mock_redis.exists.assert_awaited_once_with("myagent:x")

    @pytest.mark.asyncio
    async def test_prefix_on_clear(self, redis_backend, mock_redis):
        mock_redis.scan_iter.return_value = _async_iter([])
        await redis_backend.clear("ns:*")
        _args, kwargs = mock_redis.scan_iter.call_args
        assert kwargs.get("match") == "myagent:ns:*"

    @pytest.mark.asyncio
    async def test_custom_prefix(self, mock_redis):
        backend = _build_redis_backend(mock_redis, prefix="app:cache:")
        mock_redis.get.return_value = None
        await backend.get("test")
        mock_redis.get.assert_awaited_once_with("app:cache:test")


# ── CacheManager — factory creates Redis backend from config ─────────────


class TestCacheManagerFactory:
    """Verify CacheManager creates the correct backend from YAML config."""

    def test_factory_creates_memory_by_default(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    def test_factory_creates_memory_when_explicit(self):
        cfg = {"cache": {"backend": "memory"}}
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    def test_factory_creates_redis_when_configured(self):
        cfg = {
            "cache": {
                "backend": "redis",
                "redis_url": "redis://localhost:6379/1",
                "default_ttl": 600,
            }
        }
        mock_redis_instance = AsyncMock()
        mock_aioredis_module = MagicMock()
        mock_aioredis_module.from_url.return_value = mock_redis_instance
        with (
            patch("packages.cache.manager._load_cache_config", return_value=cfg),
            patch("redis.asyncio", mock_aioredis_module, create=True),
        ):
            mgr = CacheManager()
            assert isinstance(mgr._backend, RedisCacheBackend)
            assert mgr._backend._default_ttl == 600  # noqa: SLF001
            assert mgr._backend._redis is mock_redis_instance  # noqa: SLF001

    def test_factory_fallback_on_import_error(self):
        """If redis package is not installed, fall back to MemoryCacheBackend."""
        cfg = {"cache": {"backend": "redis"}}
        with (
            patch("packages.cache.manager._load_cache_config", return_value=cfg),
            patch.dict("sys.modules", {"redis.asyncio": None}),
        ):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    def test_factory_fallback_on_connection_error(self):
        """If Redis connection fails, fall back to MemoryCacheBackend."""
        cfg = {"cache": {"backend": "redis", "redis_url": "redis://bad-host:6379/0"}}
        mock_aioredis_module = MagicMock()
        mock_aioredis_module.from_url.side_effect = Exception("Connection refused")
        with (
            patch("packages.cache.manager._load_cache_config", return_value=cfg),
            patch("redis.asyncio", mock_aioredis_module, create=True),
        ):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)

    def test_factory_uses_config_max_size_for_memory(self):
        cfg = {"cache": {"backend": "memory", "max_size": 50, "default_ttl": 99}}
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager()
            assert mgr._backend.max_size == 50
            assert mgr._backend.default_ttl == 99


# ── CacheManager — namespaced operations via Redis backend ───────────────


class TestCacheManagerWithRedisBackend:
    """Verify CacheManager delegates namespaced operations to RedisCacheBackend.

    Key design note: CacheManager._ns_key produces ``prefix:ns:key``.  When
    this is passed to RedisCacheBackend.set / get / …, the backend applies its
    own ``_prefix``.  To avoid double-prefixing the Redis backend is configured
    with an empty prefix when managed by CacheManager.
    """

    @pytest.fixture()
    def mgr_with_redis(self, mock_redis):
        """CacheManager backed by a (mocked) RedisCacheBackend.

        The Redis backend prefix is empty because CacheManager already adds
        its own prefix via _ns_key.
        """
        # Empty prefix — CacheManager does the namespacing
        backend = _build_redis_backend(mock_redis, prefix="", default_ttl=300)

        cfg = {
            "cache": {
                "backend": "redis",
                "default_ttl": 300,
                "namespaces": {
                    "tasks": {"ttl": 60},
                    "dashboard": {"ttl": 30},
                },
            }
        }
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager(backend=backend, prefix="myagent")
        return mgr, mock_redis

    @pytest.mark.asyncio
    async def test_namespaced_set_sends_prefixed_key(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        await mgr.set("tasks", "abc", {"goal": "run"})
        call_args = mock_redis.set.call_args
        # CacheManager._ns_key => "myagent:tasks:abc", backend prefix="" => no extra prefix
        assert call_args[0][0] == "myagent:tasks:abc"
        assert json.loads(call_args[0][1]) == {"goal": "run"}
        # tasks namespace TTL is 60
        assert call_args[1]["ex"] == 60

    @pytest.mark.asyncio
    async def test_namespaced_get_reads_prefixed_key(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        mock_redis.get.return_value = json.dumps({"goal": "run"})
        result = await mgr.get("tasks", "abc")
        assert result == {"goal": "run"}
        mock_redis.get.assert_awaited_once_with("myagent:tasks:abc")

    @pytest.mark.asyncio
    async def test_namespaced_invalidate_uses_pattern(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        keys = ["myagent:tasks:k1", "myagent:tasks:k2"]
        mock_redis.scan_iter.return_value = _async_iter(keys)
        count = await mgr.invalidate("tasks")
        assert count == 2
        _a, kw = mock_redis.scan_iter.call_args
        assert kw.get("match") == "myagent:tasks:*"

    @pytest.mark.asyncio
    async def test_namespace_isolation(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        await mgr.set("tasks", "shared_key", "task_value")
        await mgr.set("dashboard", "shared_key", "dash_value")

        calls = mock_redis.set.call_args_list
        task_call = calls[0]
        dash_call = calls[1]
        assert task_call[0][0] == "myagent:tasks:shared_key"
        assert dash_call[0][0] == "myagent:dashboard:shared_key"

    @pytest.mark.asyncio
    async def test_convenience_tasks_methods(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        mock_redis.get.return_value = json.dumps([{"id": "t1"}])
        await mgr.set_tasks("h1", [{"id": "t1"}])
        result = await mgr.get_tasks("h1")

        mock_redis.set.assert_awaited_once()
        assert mock_redis.set.call_args[0][0] == "myagent:tasks:h1"
        assert result == [{"id": "t1"}]

    @pytest.mark.asyncio
    async def test_convenience_dashboard_methods(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        mock_redis.get.return_value = json.dumps({"total": 42})
        await mgr.set_dashboard({"total": 42})
        result = await mgr.get_dashboard()

        mock_redis.set.assert_awaited_once()
        assert mock_redis.set.call_args[0][0] == "myagent:dashboard:stats"
        assert result == {"total": 42}

    @pytest.mark.asyncio
    async def test_convenience_invalidate_tasks(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        keys = ["myagent:tasks:h1"]
        mock_redis.scan_iter.return_value = _async_iter(keys)
        count = await mgr.invalidate_tasks()
        assert count == 1
        _a, kw = mock_redis.scan_iter.call_args
        assert kw.get("match") == "myagent:tasks:*"

    @pytest.mark.asyncio
    async def test_convenience_invalidate_dashboard(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        keys = ["myagent:dashboard:stats"]
        mock_redis.scan_iter.return_value = _async_iter(keys)
        count = await mgr.invalidate_dashboard()
        assert count == 1
        _a, kw = mock_redis.scan_iter.call_args
        assert kw.get("match") == "myagent:dashboard:*"

    @pytest.mark.asyncio
    async def test_namespace_ttl_override(self, mgr_with_redis):
        """tasks namespace has ttl=60, dashboard has ttl=30 in config."""
        mgr, mock_redis = mgr_with_redis

        await mgr.set("tasks", "k", "v")
        tasks_ex = mock_redis.set.call_args[1]["ex"]
        assert tasks_ex == 60

        await mgr.set("dashboard", "k", "v")
        dash_ex = mock_redis.set.call_args[1]["ex"]
        assert dash_ex == 30

    @pytest.mark.asyncio
    async def test_namespace_no_ttl_uses_default(self, mgr_with_redis):
        """skills namespace has no TTL configured — backend default (300) is used."""
        mgr, mock_redis = mgr_with_redis
        await mgr.set("skills", "k", "v")
        ex_val = mock_redis.set.call_args[1]["ex"]
        assert ex_val == 300

    @pytest.mark.asyncio
    async def test_close_delegates(self, mgr_with_redis):
        mgr, mock_redis = mgr_with_redis
        await mgr._backend.close()
        mock_redis.close.assert_awaited_once()


# ── CacheManager — YAML config parsing ───────────────────────────────────


class TestCacheManagerYAMLConfig:
    """Verify CacheManager parses YAML config correctly."""

    def test_reads_namespaces(self):
        cfg = {
            "cache": {
                "backend": "memory",
                "namespaces": {
                    "tasks": {"ttl": 60},
                    "dashboard": {"ttl": 30},
                    "skills": {"ttl": 120},
                },
            }
        }
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager()
            assert mgr._namespaces == cfg["cache"]["namespaces"]

    def test_namespace_ttl_returns_configured_value(self):
        cfg = {
            "cache": {
                "namespaces": {
                    "tasks": {"ttl": 45},
                },
            }
        }
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager()
            assert mgr._ns_ttl("tasks") == 45.0

    def test_namespace_ttl_returns_none_for_unknown(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager()
            assert mgr._ns_ttl("nonexistent") is None

    def test_empty_config_uses_defaults(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager()
            assert isinstance(mgr._backend, MemoryCacheBackend)
            assert mgr._backend.max_size == 1000
            assert mgr._backend.default_ttl == 300
            assert mgr._namespaces == {}

    def test_config_with_no_namespaces_key(self):
        cfg = {"cache": {"backend": "memory", "default_ttl": 500}}
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager()
            assert mgr._namespaces == {}

    def test_config_redis_url_passed_to_backend(self):
        cfg = {
            "cache": {
                "backend": "redis",
                "redis_url": "redis://custom-host:6380/2",
                "default_ttl": 120,
            }
        }
        mock_redis_instance = AsyncMock()
        mock_aioredis_module = MagicMock()
        mock_aioredis_module.from_url.return_value = mock_redis_instance
        with (
            patch("packages.cache.manager._load_cache_config", return_value=cfg),
            patch("redis.asyncio", mock_aioredis_module, create=True),
        ):
            mgr = CacheManager()
            mock_aioredis_module.from_url.assert_called_once_with(
                "redis://custom-host:6380/2", decode_responses=True
            )

    def test_config_redis_default_url_when_not_specified(self):
        cfg = {"cache": {"backend": "redis"}}
        mock_redis_instance = AsyncMock()
        mock_aioredis_module = MagicMock()
        mock_aioredis_module.from_url.return_value = mock_redis_instance
        with (
            patch("packages.cache.manager._load_cache_config", return_value=cfg),
            patch("redis.asyncio", mock_aioredis_module, create=True),
        ):
            mgr = CacheManager()
            mock_aioredis_module.from_url.assert_called_once_with(
                "redis://localhost:6379/0", decode_responses=True
            )


# ── CacheManager — hash_query utility ────────────────────────────────────


class TestCacheManagerHashQuery:
    """Verify the deterministic hash_query utility."""

    def test_deterministic_same_params(self):
        h1 = CacheManager.hash_query({"a": 1, "b": 2})
        h2 = CacheManager.hash_query({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_params_different_hash(self):
        h1 = CacheManager.hash_query({"a": 1})
        h2 = CacheManager.hash_query({"a": 2})
        assert h1 != h2

    def test_hash_length(self):
        """hash_query returns first 32 hex chars of SHA-256."""
        h = CacheManager.hash_query({"x": 1})
        assert len(h) == 32

    def test_hash_with_nested_params(self):
        h1 = CacheManager.hash_query({"filter": {"status": "running"}, "limit": 10})
        h2 = CacheManager.hash_query({"limit": 10, "filter": {"status": "running"}})
        assert h1 == h2

    def test_hash_with_list_param(self):
        h1 = CacheManager.hash_query({"ids": [1, 2, 3]})
        h2 = CacheManager.hash_query({"ids": [1, 2, 3]})
        assert h1 == h2

    def test_hash_with_different_lists(self):
        h1 = CacheManager.hash_query({"ids": [1, 2, 3]})
        h2 = CacheManager.hash_query({"ids": [3, 2, 1]})
        assert h1 != h2

    def test_hash_is_hex_string(self):
        h = CacheManager.hash_query({"k": "v"})
        assert all(c in "0123456789abcdef" for c in h)


# ── RedisCacheBackend — _prefixed helper ─────────────────────────────────


class TestRedisCacheBackendPrefixed:
    """Verify the _prefixed key construction."""

    def test_prefixed_default(self):
        backend = object.__new__(RedisCacheBackend)
        backend._prefix = "myagent:"  # noqa: SLF001
        backend._healthy = True  # noqa: SLF001
        assert backend._prefixed("key") == "myagent:key"

    def test_prefixed_custom(self):
        backend = object.__new__(RedisCacheBackend)
        backend._prefix = "app:v2:"  # noqa: SLF001
        backend._healthy = True  # noqa: SLF001
        assert backend._prefixed("test") == "app:v2:test"

    def test_prefixed_with_colon_in_key(self):
        backend = object.__new__(RedisCacheBackend)
        backend._prefix = "myagent:"  # noqa: SLF001
        backend._healthy = True  # noqa: SLF001
        assert backend._prefixed("ns:sub:key") == "myagent:ns:sub:key"

    def test_prefixed_empty(self):
        """Empty prefix passes the key through unchanged."""
        backend = object.__new__(RedisCacheBackend)
        backend._prefix = ""  # noqa: SLF001
        backend._healthy = True  # noqa: SLF001
        assert backend._prefixed("ns:key") == "ns:key"


# ── CacheManager — ns_key and ns_pattern helpers ─────────────────────────


class TestCacheManagerHelpers:
    """Verify CacheManager internal key construction helpers."""

    def test_ns_key(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager(prefix="myagent")
            assert mgr._ns_key("tasks", "abc") == "myagent:tasks:abc"

    def test_ns_pattern(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager(prefix="myagent")
            assert mgr._ns_pattern("tasks") == "myagent:tasks:*"

    def test_ns_key_custom_prefix(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager(prefix="app")
            assert mgr._ns_key("skills", "h1") == "app:skills:h1"

    def test_ns_pattern_custom_prefix(self):
        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager(prefix="app")
            assert mgr._ns_pattern("dashboard") == "app:dashboard:*"


# ── RedisCacheBackend — constructor and import error ──────────────────────


class TestRedisCacheBackendInit:
    """Verify constructor behavior when redis package is/isn't available."""

    def test_init_raises_on_missing_redis_package(self):
        """ImportError should be raised if redis.asyncio is not importable."""
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            with pytest.raises(ImportError, match="redis package is required"):
                RedisCacheBackend()

    def test_init_succeeds_with_mocked_redis(self):
        """Constructor should succeed when redis.asyncio is importable."""
        mock_client = AsyncMock()
        mock_aioredis_module = MagicMock()
        mock_aioredis_module.from_url.return_value = mock_client
        with patch("redis.asyncio", mock_aioredis_module, create=True):
            backend = RedisCacheBackend(
                redis_url="redis://localhost:6379/0",
                prefix="test:",
                default_ttl=120,
            )
            assert backend._prefix == "test:"  # noqa: SLF001
            assert backend._default_ttl == 120  # noqa: SLF001
            assert backend._redis is mock_client  # noqa: SLF001

    def test_init_default_params(self):
        mock_client = AsyncMock()
        mock_aioredis_module = MagicMock()
        mock_aioredis_module.from_url.return_value = mock_client
        with patch("redis.asyncio", mock_aioredis_module, create=True):
            backend = RedisCacheBackend()
            assert backend._prefix == "myagent:"  # noqa: SLF001
            assert backend._default_ttl == 300  # noqa: SLF001
            mock_aioredis_module.from_url.assert_called_once_with(
                "redis://localhost:6379/0", decode_responses=True
            )


# ── CacheManager — full round-trip with Redis backend ────────────────────


class TestCacheManagerRedisRoundTrip:
    """End-to-end: set through CacheManager, verify the exact bytes sent to Redis."""

    @pytest.mark.asyncio
    async def test_round_trip_set_get(self):
        mock_redis = _make_mock_redis()
        # Empty prefix — CacheManager handles namespacing
        backend = _build_redis_backend(mock_redis, prefix="", default_ttl=300)

        cfg = {
            "cache": {
                "backend": "redis",
                "namespaces": {"tasks": {"ttl": 60}},
            }
        }
        with patch("packages.cache.manager._load_cache_config", return_value=cfg):
            mgr = CacheManager(backend=backend, prefix="myagent")

        # Set a value
        await mgr.set("tasks", "query1", {"results": [1, 2, 3]})

        # Verify what was sent to Redis
        set_call = mock_redis.set.call_args
        assert set_call[0][0] == "myagent:tasks:query1"
        assert json.loads(set_call[0][1]) == {"results": [1, 2, 3]}
        assert set_call[1]["ex"] == 60

        # Simulate Redis returning the same data
        mock_redis.get.return_value = set_call[0][1]
        result = await mgr.get("tasks", "query1")
        assert result == {"results": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_round_trip_invalidate(self):
        mock_redis = _make_mock_redis()
        backend = _build_redis_backend(mock_redis, prefix="", default_ttl=300)

        with patch("packages.cache.manager._load_cache_config", return_value={}):
            mgr = CacheManager(backend=backend, prefix="myagent")

        # Set two keys
        await mgr.set("tasks", "a", 1)
        await mgr.set("tasks", "b", 2)

        # Invalidate tasks — scan_iter returns the two keys
        mock_redis.scan_iter.return_value = _async_iter([
            "myagent:tasks:a",
            "myagent:tasks:b",
        ])
        count = await mgr.invalidate("tasks")
        assert count == 2
        # Deletes may be batched into one call — verify key coverage.
        deleted = set()
        for call in mock_redis.delete.await_args_list:
            for a in call.args:
                deleted.update(a if isinstance(a, list) else [a])
        assert {"myagent:tasks:a", "myagent:tasks:b"} <= deleted
