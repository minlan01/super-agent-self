"""Rate Limiting Middleware — in-memory sliding window rate limiter with per-route support."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

import yaml
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

MAX_CLIENTS = 10_000
_SHARD_COUNT = 32

EXEMPT_PREFIXES: tuple[str, ...] = (
    "/ws/",
    "/ws",
    "/health",
    "/api/v1/health",
    "/api/v1/metrics",
)

# Module-level reference to the active RateLimiter instance.
# Set once during app startup so admin routes can access it.
_active_limiter: RateLimiter | None = None


def set_active_limiter(limiter: RateLimiter) -> None:
    """Register the active RateLimiter instance for admin access."""
    global _active_limiter
    _active_limiter = limiter


def get_active_limiter() -> RateLimiter | None:
    """Return the active RateLimiter instance (or None if not registered)."""
    return _active_limiter


class RateLimiter(BaseHTTPMiddleware):
    """Sliding window rate limiter per client IP with per-route support.

    Configurable requests-per-minute limit. Returns 429 when exceeded.
    Thread-safe with asyncio.Lock. Bounded memory with LRU eviction.

    Per-route limits are provided via *route_limits*: a dict mapping a route
    prefix string to a ``(max_requests, window_seconds)`` tuple. The longest
    matching prefix wins. If no route_limits are supplied the global
    ``max_requests`` / ``window_seconds`` is used for every route (backward
    compatible behaviour).

    When *config_path* is provided, the limiter supports hot-reload:
    - Poll-based: checks the file mtime every 30 s during ``dispatch()``.
    - Manual: call ``reload_config()`` (e.g. from an admin endpoint).
    """

    def __init__(
        self,
        app: Any,
        max_requests: int = 60,
        window_seconds: int = 60,
        route_limits: dict[str, tuple[int, int]] | None = None,
        config_path: str | None = None,
        trusted_proxies: list[str] | None = None,
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.route_limits: dict[str, tuple[int, int]] = route_limits or {}
        self._rebuild_sorted_prefixes()
        self._requests: dict[str, dict[str, list[float]]] = {}
        self._locks: list[asyncio.Lock] = [asyncio.Lock() for _ in range(_SHARD_COUNT)]
        # RLock: _check_config_reload() holds this lock while calling
        # _load_config(), which acquires it again — a plain Lock deadlocks
        # the poll-reload path (same thread, double acquire).
        self._config_lock = threading.RLock()
        self.trusted_proxies: set[str] = set(trusted_proxies or [])

        # Hot-reload state
        self._config_path: str | None = config_path
        self._config_mtime: float = 0.0
        self._reload_interval: float = 30.0  # check every 30 seconds
        self._last_reload_check: float = 0.0

        # If a config_path is given, load it and initialise mtime
        if config_path:
            self._load_config()
            try:
                self._config_mtime = os.path.getmtime(config_path)
            except OSError:
                pass

        # Register self as the active limiter so admin routes can access it
        set_active_limiter(self)

    # ------------------------------------------------------------------
    # Config loading / hot-reload
    # ------------------------------------------------------------------

    def _rebuild_sorted_prefixes(self) -> None:
        """Re-sort prefix keys after a config change."""
        self._sorted_prefixes: list[str] = sorted(
            self.route_limits.keys(), key=len, reverse=True
        )

    def _validate_config(self, data: dict) -> None:
        """Validate the parsed YAML structure.

        Raises ``ValueError`` with a descriptive message for any problem.
        """
        if not isinstance(data, dict):
            raise ValueError("Config top-level must be a mapping")
        rl = data.get("rate_limits")
        if rl is None:
            raise ValueError("Missing 'rate_limits' key")
        if not isinstance(rl, dict):
            raise ValueError("'rate_limits' must be a mapping")

        # Validate default
        default = rl.get("default")
        if default is None:
            raise ValueError("Missing 'rate_limits.default'")
        if not isinstance(default, dict):
            raise ValueError("'rate_limits.default' must be a mapping")
        if not isinstance(default.get("max_requests"), int) or default["max_requests"] <= 0:
            raise ValueError("'default.max_requests' must be a positive integer")
        if not isinstance(default.get("window_seconds"), int) or default["window_seconds"] <= 0:
            raise ValueError("'default.window_seconds' must be a positive integer")

        # Validate routes
        routes = rl.get("routes")
        if routes is not None:
            if not isinstance(routes, dict):
                raise ValueError("'rate_limits.routes' must be a mapping")
            for prefix, cfg in routes.items():
                if not isinstance(cfg, dict):
                    raise ValueError(f"Route '{prefix}' config must be a mapping")
                if "max_requests" not in cfg:
                    raise ValueError(f"Route '{prefix}' missing 'max_requests'")
                if "window_seconds" not in cfg:
                    raise ValueError(f"Route '{prefix}' missing 'window_seconds'")
                if not isinstance(cfg["max_requests"], int) or cfg["max_requests"] <= 0:
                    raise ValueError(f"Route '{prefix}' max_requests must be a positive integer")
                if not isinstance(cfg["window_seconds"], int) or cfg["window_seconds"] <= 0:
                    raise ValueError(f"Route '{prefix}' window_seconds must be a positive integer")

    def _load_config(self) -> None:
        """Load (or reload) the YAML config and apply validated limits.

        On validation failure the previous config is kept intact.
        Thread-safe: uses a threading.Lock to prevent concurrent reloads
        from corrupting state.
        """
        if not self._config_path:
            return
        with self._config_lock:
            try:
                with open(self._config_path, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                self._validate_config(data)

                rl = data["rate_limits"]
                default_cfg = rl["default"]
                new_default = (
                    int(default_cfg["max_requests"]),
                    int(default_cfg["window_seconds"]),
                )
                new_route_limits: dict[str, tuple[int, int]] = {}
                for prefix, cfg in rl.get("routes", {}).items():
                    new_route_limits[prefix] = (
                        int(cfg["max_requests"]),
                        int(cfg["window_seconds"]),
                    )

                self.max_requests, self.window_seconds = new_default
                self.route_limits = new_route_limits
                self._rebuild_sorted_prefixes()
                logger.info("Rate limit config loaded from %s", self._config_path)
            except (yaml.YAMLError, OSError) as exc:
                logger.error("Failed to load rate_limits config: %s", exc)
            except ValueError as exc:
                logger.error("Invalid rate_limits config, keeping previous: %s", exc)

    def _check_config_reload(self) -> None:
        """Poll-based config reload -- checks file mtime."""
        if not self._config_path:
            return
        now = time.time()
        if now - self._last_reload_check < self._reload_interval:
            return
        self._last_reload_check = now
        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime > self._config_mtime:
                with self._config_lock:
                    old_limits = dict(self.route_limits)
                    self._load_config()
                    self._config_mtime = mtime
                    if self.route_limits != old_limits:
                        logger.info("rate_limits.yaml reloaded (poll)")
        except OSError:
            pass

    def reload_config(self) -> dict:
        """Manual reload -- called by admin endpoint.

        Returns the new config dict regardless of success.
        """
        self._load_config()
        if self._config_path:
            try:
                self._config_mtime = os.path.getmtime(self._config_path)
            except OSError:
                pass
        return self.get_current_config()

    def get_current_config(self) -> dict:
        """Return current config without reloading."""
        return {
            "limits": dict(self.route_limits),
            "default": (self.max_requests, self.window_seconds),
        }

    # ------------------------------------------------------------------
    # Route matching
    # ------------------------------------------------------------------

    @staticmethod
    def _is_exempt(path: str) -> bool:
        """Return True for paths that should bypass rate limiting entirely."""
        for prefix in EXEMPT_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return True
        return False

    def _get_limit(self, path: str) -> tuple[int, int]:
        """Return (max_requests, window_seconds) for *path*.

        Uses longest-prefix match against *route_limits*. Falls back to the
        global ``max_requests`` / ``window_seconds`` when nothing matches.
        """
        for prefix in self._sorted_prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return self.route_limits[prefix]
        return self.max_requests, self.window_seconds

    def _bucket_key(self, path: str) -> str:
        """Determine the bucket key for a request path.

        For per-route limits we group by the matched prefix so that, e.g.,
        ``/api/v1/auth/login`` and ``/api/v1/auth/register`` share the same
        quota under the ``/api/v1/auth`` rule.
        """
        for prefix in self._sorted_prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return prefix
        return "__default__"

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def _get_client_id(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        from_trusted = (
            not self.trusted_proxies
            or (request.client and request.client.host in self.trusted_proxies)
        )
        if forwarded and from_trusted:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_allowed(self, client_id: str, path: str) -> bool:
        """Check whether *client_id* is allowed to hit *path*."""
        max_req, win_sec = self._get_limit(path)
        bucket = self._bucket_key(path)
        now = time.time()
        cutoff = now - win_sec

        client_buckets = self._requests.get(client_id, {})
        timestamps = client_buckets.get(bucket, [])
        # Clean old entries
        timestamps = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= max_req:
            # Still write back cleaned timestamps so the window can slide
            # even when the client is being rate-limited
            client_buckets[bucket] = timestamps
            self._requests[client_id] = client_buckets
            return False

        timestamps.append(now)
        client_buckets[bucket] = timestamps
        self._requests[client_id] = client_buckets

        # Evict stale clients if over limit
        if len(self._requests) > MAX_CLIENTS:
            stale = [
                cid
                for cid, buckets in self._requests.items()
                if not buckets or all(not ts or ts[-1] < cutoff for ts in buckets.values())
            ]
            for cid in stale:
                del self._requests[cid]

        return True

    # ------------------------------------------------------------------
    # Middleware entry point
    # ------------------------------------------------------------------

    def _get_shard(self, client_id: str) -> asyncio.Lock:
        """Get the lock shard for a client ID to reduce contention."""
        return self._locks[hash(client_id) % _SHARD_COUNT]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Hot-reload check (poll-based, cheap when interval not elapsed)
        self._check_config_reload()

        # Skip rate limiting for health checks and WebSocket
        if self._is_exempt(path):
            return await call_next(request)

        client_id = self._get_client_id(request)
        async with self._get_shard(client_id):
            allowed = self._is_allowed(client_id, path)

        if not allowed:
            max_req, win_sec = self._get_limit(path)
            return Response(
                content='{"success":false,"message":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(win_sec)},
            )

        return await call_next(request)
