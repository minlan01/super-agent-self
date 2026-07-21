"""Capability Token -- HMAC-SHA256 signed execution authorization."""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class NonceStore(Protocol):
    """Protocol for nonce storage backends."""

    def seen(self, nonce: str) -> bool: ...
    def mark(self, nonce: str, ttl: float) -> None: ...


class _InMemoryNonceStore:
    """Thread-safe in-memory nonce store (single-process)."""

    def __init__(self, ttl: float = 600, cleanup_interval: float = 60):
        self._store: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = 0.0

    def seen(self, nonce: str) -> bool:
        with self._lock:
            return nonce in self._store

    def mark(self, nonce: str, ttl: float | None = None) -> None:
        effective_ttl = ttl or self._ttl
        with self._lock:
            self._store[nonce] = time.time()
            now = time.time()
            if now - self._last_cleanup > self._cleanup_interval:
                self._last_cleanup = now
                expired = [k for k, v in self._store.items() if now - v > effective_ttl]
                for k in expired:
                    del self._store[k]


class _RedisNonceStore:
    """Redis-backed nonce store for multi-process deployments."""

    def __init__(self, redis_client, prefix="cap_nonce:"):
        self._redis = redis_client
        self._prefix = prefix

    def seen(self, nonce: str) -> bool:
        return bool(self._redis.exists(f"{self._prefix}{nonce}"))

    def mark(self, nonce: str, ttl: float = 600) -> None:
        self._redis.setex(f"{self._prefix}{nonce}", int(ttl), "1")


# Global default nonce store (lazy-initialized; in-memory unless Redis is configured)
_nonce_store: NonceStore | None = None


def _get_nonce_store() -> NonceStore:
    """Return the global nonce store, initializing on first access."""
    global _nonce_store
    if _nonce_store is None:
        _nonce_store = _InMemoryNonceStore()
    return _nonce_store


def create_nonce_store() -> NonceStore:
    """Create the appropriate nonce store based on config."""
    try:
        from packages.config import get_settings
        settings = get_settings()
        import yaml
        from pathlib import Path
        cache_yaml = Path("configs/cache.yaml")
        if cache_yaml.exists():
            with open(cache_yaml) as f:
                cfg = yaml.safe_load(f)
            if cfg and cfg.get("cache", {}).get("backend") == "redis":
                import redis
                url = cfg["cache"].get("redis_url", "redis://localhost:6379/0")
                client = redis.from_url(url, decode_responses=True)
                logger.info("Nonce store: Redis backend (%s)", url)
                return _RedisNonceStore(client)
    except Exception as e:
        logger.debug("Falling back to in-memory nonce store: %s", e)
    return _InMemoryNonceStore()


@dataclass
class CapabilityToken:
    task_id: str
    step_id: str
    tool_name: str
    args_hash: str  # SHA256 hash of args, truncated
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    issued_at: float = field(default_factory=time.time)
    expire_minutes: int = 5

    @property
    def expires_at(self) -> float:
        return self.issued_at + self.expire_minutes * 60

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expire_minutes": self.expire_minutes,
        }


class TokenIssuer:
    def __init__(self, secret_key: str, expire_minutes: int | None = None):
        self.secret_key = secret_key.encode("utf-8")
        if expire_minutes is not None:
            self.expire_minutes = expire_minutes
        else:
            try:
                from packages.config import get_settings
                self.expire_minutes = get_settings().security.capability_token_expire_minutes
            except Exception as e:
                logger.warning("Failed to read capability_token_expire_minutes from config, using default: %s", e)
                self.expire_minutes = 5

    def compute_args_hash(self, args: dict[str, Any]) -> str:
        """Compute truncated SHA256 hash of args."""
        raw = json.dumps(args, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    def issue(self, task_id: str, step_id: str, tool_name: str, args: dict[str, Any]) -> str:
        """Issue a signed capability token. Returns token string."""
        args_hash = self.compute_args_hash(args)
        token = CapabilityToken(
            task_id=task_id,
            step_id=step_id,
            tool_name=tool_name,
            args_hash=args_hash,
            expire_minutes=self.expire_minutes,
        )
        payload = token.to_payload()
        signature = self._sign(payload)
        payload["signature"] = signature
        # Encode as base64 JSON
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    def verify(self, token_str: str, task_id: str, step_id: str, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Verify a capability token. Returns (valid, reason)."""
        try:
            payload = json.loads(base64.urlsafe_b64decode(token_str.encode()).decode())
        except Exception as e:
            return False, f"Invalid token format: {e}"

        # Verify signature
        signature = payload.pop("signature", None)
        if signature is None:
            return False, "Token missing signature"

        expected_sig = self._sign(payload)
        if not hmac.compare_digest(signature, expected_sig):
            return False, "Token signature mismatch (tampered)"

        # Verify fields
        if payload.get("task_id") != task_id:
            return False, "Token task_id mismatch"
        if payload.get("step_id") != step_id:
            return False, "Token step_id mismatch"
        if payload.get("tool_name") != tool_name:
            return False, "Token tool_name mismatch"

        # Verify args hash
        expected_hash = self.compute_args_hash(args)
        if payload.get("args_hash") != expected_hash:
            return False, "Token args_hash mismatch"

        # Verify expiry
        issued_at = payload.get("issued_at", 0)
        expire_minutes = payload.get("expire_minutes", 5)
        if time.time() > issued_at + expire_minutes * 60:
            return False, "Token expired"

        # Verify nonce (replay protection)
        nonce = payload.get("nonce", "")
        if not nonce:
            return False, "Token missing nonce"
        ns = _get_nonce_store()
        if ns.seen(nonce):
            return False, "Token already used (replay detected)"
        issued_at = payload.get("issued_at", 0)
        expire_minutes = payload.get("expire_minutes", 5)
        nonce_ttl = expire_minutes * 60 * 2  # TTL = 2× token lifetime
        ns.mark(nonce, ttl=nonce_ttl)

        return True, "OK"

    def _sign(self, payload: dict) -> str:
        """Sign payload with HMAC-SHA256."""
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hmac.HMAC(self.secret_key, raw, hashlib.sha256).hexdigest()


def configure_nonce_store(store: NonceStore) -> None:
    """Replace the global nonce store (e.g. with Redis-backed store for multi-process)."""
    global _nonce_store
    _nonce_store = store
