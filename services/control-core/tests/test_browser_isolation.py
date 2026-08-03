"""Tests for browser isolation (P3.5) — egress policy + context isolation."""

import os
import tempfile

import pytest

from packages.security.browser_isolation import (
    BrowserContextManager,
    EgressPolicy,
    IsolationKey,
    validate_navigation,
)


class TestEgressPolicy:
    def test_public_url_allowed(self):
        policy = EgressPolicy()
        result = policy.check("https://example.com/page")
        assert result.allowed is True

    def test_loopback_blocked(self):
        policy = EgressPolicy()
        result = policy.check("http://127.0.0.1:8080/admin")
        assert result.allowed is False
        assert "127.0.0.1" in result.reason or "loopback" in result.reason.lower()

    def test_localhost_blocked(self):
        policy = EgressPolicy()
        result = policy.check("http://localhost:3000/")
        assert result.allowed is False

    def test_metadata_endpoint_blocked(self):
        """169.254.169.254 (cloud metadata) must be blocked."""
        policy = EgressPolicy()
        result = policy.check("http://169.254.169.254/latest/meta-data/")
        assert result.allowed is False

    def test_private_network_blocked(self):
        policy = EgressPolicy()
        result = policy.check("http://192.168.1.1/admin")
        assert result.allowed is False

    def test_denylist_blocks_url(self):
        policy = EgressPolicy(denylist=["evil.com", "malware.site"])
        result = policy.check("https://evil.com/payload")
        assert result.allowed is False
        assert "denylist" in result.reason.lower()

    def test_allowlist_blocks_unlisted(self):
        policy = EgressPolicy(allowlist=["trusted.com", "api.trusted.com"])
        result = policy.check("https://untrusted.com/page")
        assert result.allowed is False
        assert "allowlist" in result.reason.lower()

    def test_allowlist_allows_listed(self):
        policy = EgressPolicy(allowlist=["trusted.com"])
        result = policy.check("https://trusted.com/page")
        assert result.allowed is True

    def test_allowlist_with_ssrf_still_blocks_private(self):
        """Even with allowlist, SSRF check still runs."""
        policy = EgressPolicy(allowlist=["127.0.0.1"])
        result = policy.check("http://127.0.0.1:8080/")
        # Allowlist matches, but SSRF blocks loopback
        assert result.allowed is False

    def test_non_http_scheme_blocked(self):
        policy = EgressPolicy()
        result = policy.check("file:///etc/passwd")
        assert result.allowed is False

    def test_javascript_scheme_blocked(self):
        policy = EgressPolicy()
        result = policy.check("javascript:alert(1)")
        assert result.allowed is False

    def test_validate_navigation_default(self):
        """Default validation uses SSRF guard only."""
        result = validate_navigation("https://example.com")
        assert result.allowed is True
        result = validate_navigation("http://127.0.0.1")
        assert result.allowed is False


class TestIsolationKey:
    def test_different_tasks_different_partitions(self):
        k1 = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        k2 = IsolationKey(tenant_id="t1", task_id="task-2", step_id="s1")
        assert k1.partition_id() != k2.partition_id()

    def test_same_task_same_partition(self):
        k1 = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        k2 = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        assert k1.partition_id() == k2.partition_id()

    def test_different_tenants_different_partitions(self):
        k1 = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        k2 = IsolationKey(tenant_id="t2", task_id="task-1", step_id="s1")
        assert k1.partition_id() != k2.partition_id()

    def test_partition_id_is_hex(self):
        k = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        pid = k.partition_id()
        assert len(pid) == 16
        int(pid, 16)  # Should not raise


class TestBrowserContextManager:
    @pytest.fixture()
    def mgr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield BrowserContextManager(data_root=os.path.join(tmpdir, "profiles"))

    def test_partition_dir_created(self, mgr):
        key = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        part = mgr.get_partition_dir(key)
        assert part.exists()
        assert part.is_dir()
        assert "t1" in str(part)

    def test_partition_dir_reused(self, mgr):
        key = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        p1 = mgr.get_partition_dir(key)
        p2 = mgr.get_partition_dir(key)
        assert p1 == p2

    def test_no_active_partitions_initially(self, mgr):
        assert mgr.get_active_partitions() == []

    def test_close_context_without_create_is_noop(self, mgr):
        """Closing a context that was never created should not error."""
        import asyncio
        key = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        asyncio.run(mgr.close_context(key))

    def test_close_all_wipes_storage(self, mgr):
        """close_all removes all partition directories."""
        import asyncio
        key1 = IsolationKey(tenant_id="t1", task_id="task-1", step_id="s1")
        key2 = IsolationKey(tenant_id="t1", task_id="task-2", step_id="s1")

        d1 = mgr.get_partition_dir(key1)
        d2 = mgr.get_partition_dir(key2)
        assert d1.exists()
        assert d2.exists()

        asyncio.run(mgr.close_all())

        # Partition dirs should be wiped
        assert not d1.exists()
        assert not d2.exists()
