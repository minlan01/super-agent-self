r"""Browser isolation — per-task Cookie/storage isolation + egress policy.

Spec §P3.4: browser tools must use isolated contexts per task.  Cookies,
localStorage, and session data must NOT be shared between tasks.

This module provides:
  - BrowserContextManager: creates isolated Playwright contexts per (tenant, task)
  - EgressPolicy: validates outbound URLs before browser navigation
  - StoragePartition: maps (tenant, task) -> isolated storage state

Design:
  - Each task gets its own BrowserContext with a unique user_data_dir.
  - On task completion, the context is closed and storage is wiped.
  - Egress is validated via ssrf_guard.validate_url() before any navigation.
  - Allowlist/denylist can be configured per tenant.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from packages.policy.ssrf_guard import validate_url

logger = structlog.get_logger()

# Default browser data root (each task gets a subdirectory).
_DEFAULT_BROWSER_DATA_ROOT = "data/browser_profiles"


@dataclass
class IsolationKey:
    """Uniquely identifies an isolated browser context."""
    tenant_id: str
    task_id: str
    step_id: str

    def partition_id(self) -> str:
        """Generate a deterministic partition ID for storage directory naming."""
        raw = f"{self.tenant_id}:{self.task_id}:{self.step_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class EgressDecision:
    """Result of an egress policy check."""
    allowed: bool
    url: str
    reason: str = ""
    resolved_ip: str | None = None


class EgressPolicy:
    """Validates outbound URLs before browser navigation.

    Combines SSRF guard (blocks private/loopback/metadata) with optional
    tenant-specific allowlist/denylist.
    """

    def __init__(
        self,
        allowlist: list[str] | None = None,
        denylist: list[str] | None = None,
        resolve_dns: bool = True,
    ):
        self.allowlist = allowlist or []
        self.denylist = denylist or []
        self.resolve_dns = resolve_dns

    def check(self, url: str) -> EgressDecision:
        """Validate a URL for outbound browser navigation.

        Order of checks:
          1. Denylist (if URL hostname matches any denylist entry, block)
          2. Allowlist (if set and URL hostname doesn't match any, block)
          3. SSRF guard (blocks private/loopback/metadata IPs)
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        # 1. Denylist check (hostname-based, not substring)
        for pattern in self.denylist:
            if hostname == pattern or hostname.endswith("." + pattern):
                return EgressDecision(
                    allowed=False, url=url,
                    reason=f"URL hostname matches denylist: {pattern}",
                )

        # 2. Allowlist check (hostname-based, if configured)
        if self.allowlist:
            if not any(
                hostname == pat or hostname.endswith("." + pat)
                for pat in self.allowlist
            ):
                return EgressDecision(
                    allowed=False, url=url,
                    reason=f"URL hostname not in allowlist: {hostname}",
                )

        # 3. SSRF guard
        ok, reason = validate_url(url, resolve_dns=self.resolve_dns)
        if not ok:
            return EgressDecision(allowed=False, url=url, reason=reason)

        return EgressDecision(allowed=True, url=url)


class BrowserContextManager:
    """Manages isolated Playwright browser contexts per task.

    Each (tenant, task) pair gets:
      - A unique storage partition directory
      - An isolated BrowserContext (no shared cookies/localStorage)
      - Automatic cleanup on task completion

    Usage:
        mgr = BrowserContextManager()
        ctx = await mgr.create_context(key, browser)
        # ... use ctx for navigation ...
        await mgr.close_context(key)  # wipes storage
    """

    def __init__(self, data_root: str | Path = _DEFAULT_BROWSER_DATA_ROOT):
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._contexts: dict[str, Any] = {}  # partition_id -> BrowserContext
        self._partitions: dict[str, Path] = {}  # partition_id -> user_data_dir

    def get_partition_dir(self, key: IsolationKey) -> Path:
        """Get (or create) the isolated storage directory for a task."""
        pid = key.partition_id()
        if pid not in self._partitions:
            part_dir = self.data_root / key.tenant_id / pid
            part_dir.mkdir(parents=True, exist_ok=True)
            self._partitions[pid] = part_dir
        return self._partitions[pid]

    async def create_context(
        self,
        key: IsolationKey,
        browser: Any,
        *,
        headless: bool = True,
    ) -> Any:
        """Create an isolated browser context for a task.

        Args:
            key: Isolation key (tenant + task + step).
            browser: A Playwright Browser instance.
            headless: Whether to run headless.

        Returns:
            A Playwright BrowserContext with isolated storage.
        """
        pid = key.partition_id()

        # If a context already exists for this partition, return it.
        if pid in self._contexts:
            logger.warning(
                "Context already exists for partition %s, reusing", pid,
            )
            return self._contexts[pid]

        part_dir = self.get_partition_dir(key)

        # Create context with explicit storage_state path for isolation.
        # Each context gets its own cookie jar and localStorage.
        context = await browser.new_context(
            accept_downloads=True,
            ignore_https_errors=False,
            user_agent=(
                "Mozilla/5.0 (compatible; ZcodeAgent/1.0; "
                f"+https://zcode.local/bot/{key.tenant_id})"
            ),
            viewport={"width": 1280, "height": 720},
            storage_state=None,  # Start fresh, no shared state
        )

        # Set extra HTTP headers to identify the task.
        await context.set_extra_http_headers({
            "X-Zcode-Tenant": key.tenant_id,
            "X-Zcode-Task": key.task_id,
        })

        self._contexts[pid] = context
        logger.info(
            "Browser context created: partition=%s tenant=%s task=%s",
            pid, key.tenant_id, key.task_id,
        )
        return context

    async def close_context(self, key: IsolationKey, *, wipe_storage: bool = True) -> None:
        """Close a browser context and optionally wipe its storage.

        This ensures no Cookie/localStorage leaks to the next task.
        """
        pid = key.partition_id()
        ctx = self._contexts.pop(pid, None)

        if ctx is not None:
            # Clear all storage before closing.
            try:
                for page in ctx.pages:
                    await page.context.clear_cookies()
            except Exception:
                pass
            await ctx.close()
            logger.info("Browser context closed: partition=%s", pid)

        if wipe_storage:
            part_dir = self._partitions.pop(pid, None)
            if part_dir is not None and part_dir.exists():
                shutil.rmtree(str(part_dir), ignore_errors=True)
                logger.debug("Storage wiped: %s", part_dir)

    async def close_all(self) -> None:
        """Close all open contexts and wipe all storage (e.g., on shutdown)."""
        # Close all browser contexts.
        for pid in list(self._contexts.keys()):
            ctx = self._contexts.pop(pid, None)
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass

        # Wipe ALL partition directories (including ones created via
        # get_partition_dir but never opened as a context).
        for pid in list(self._partitions.keys()):
            part_dir = self._partitions.pop(pid, None)
            if part_dir is not None and part_dir.exists():
                shutil.rmtree(str(part_dir), ignore_errors=True)

    def get_active_partitions(self) -> list[str]:
        """Return list of active partition IDs (for monitoring)."""
        return list(self._contexts.keys())


def validate_navigation(
    url: str,
    egress_policy: EgressPolicy | None = None,
) -> EgressDecision:
    """Validate a URL before browser navigation.

    This is the canonical entry point for all browser URL checks.
    If no egress_policy is provided, uses the default SSRF-only check.
    """
    if egress_policy is not None:
        return egress_policy.check(url)

    # Default: SSRF guard only.
    ok, reason = validate_url(url, resolve_dns=True)
    return EgressDecision(allowed=ok, url=url, reason=reason)
