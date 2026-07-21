"""Unit tests for Policy Engine — ToolRegistry, risk_rules, TokenIssuer, PolicyEngine."""

import json
import time
from unittest.mock import patch

import pytest

from packages.policy import risk_rules
from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine, PolicyResult
from packages.policy.tool_registry import ToolRegistry

# ── ToolRegistry tests ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestToolRegistry:
    def test_loads_from_config(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        # Should have loaded tools from the config
        assert registry.is_registered("browser.open")
        assert registry.is_registered("file.read")
        assert registry.is_registered("shell.run")

    def test_shell_run_disabled(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        assert registry.is_enabled("shell.run") is False

    def test_browser_open_enabled(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        assert registry.is_enabled("browser.open") is True

    def test_personal_only_tool_enterprise_unavailable(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        # file.search is edition: [personal]
        assert registry.is_available_for_edition("file.search", "enterprise") is False

    def test_personal_only_tool_personal_available(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        assert registry.is_available_for_edition("file.search", "personal") is True

    def test_all_edition_tool_available_everywhere(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        assert registry.is_available_for_edition("browser.open", "enterprise") is True
        assert registry.is_available_for_edition("browser.open", "personal") is True

    def test_get_tool_returns_definition(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        tool = registry.get_tool("browser.open")
        assert tool is not None
        assert tool.name == "browser.open"
        assert tool.category == "browser"
        assert tool.risk_level == "low"

    def test_get_tool_unknown_returns_none(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        assert registry.get_tool("nonexistent") is None

    def test_get_risk_level(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        assert registry.get_risk_level("browser.open") == "low"
        assert registry.get_risk_level("shell.run") == "critical"
        assert registry.get_risk_level("nonexistent") is None

    def test_list_tools_returns_enabled_only(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        tools = registry.list_tools(enabled_only=True)
        for t in tools:
            assert t.enabled is True

    def test_get_tools_summary_structure(self):
        registry = ToolRegistry(config_path="configs/tools.yaml")
        summary = registry.get_tools_summary(edition="enterprise")
        assert isinstance(summary, list)
        assert len(summary) > 0
        for item in summary:
            assert "name" in item
            assert "description" in item
            assert "params" in item
            assert "required_params" in item

    def test_missing_config_file_graceful(self):
        registry = ToolRegistry(config_path="configs/nonexistent.yaml")
        assert registry.is_registered("browser.open") is False


# ── risk_rules tests ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestRiskRules:
    def test_check_url_allowed_safe(self):
        ok, reason = risk_rules.check_url_allowed(
            "https://example.com",
            ["https?://localhost(:\\d+)?(/.*)?$"],
        )
        assert ok is True
        assert reason == ""

    def test_check_url_allowed_localhost_rejected(self):
        ok, reason = risk_rules.check_url_allowed(
            "http://localhost:8080/api",
            ["https?://localhost(:\\d+)?(/.*)?$"],
        )
        assert ok is False
        assert "forbidden pattern" in reason

    def test_check_url_allowed_127_rejected(self):
        ok, reason = risk_rules.check_url_allowed(
            "http://127.0.0.1:3000",
            ["https?://127\\.0\\.0\\.\\d+(:\\d+)?(/.*)?$"],
        )
        assert ok is False

    def test_check_url_allowed_private_network_rejected(self):
        ok, reason = risk_rules.check_url_allowed(
            "http://192.168.1.1/admin",
            ["https?://192\\.168\\.\\d+\\.\\d+(:\\d+)?(/.*)?$"],
        )
        assert ok is False

    def test_check_forbidden_path_safe(self):
        ok, reason = risk_rules.check_forbidden_path(
            "workspace/output.txt",
            ["/etc/", "/root/", "C:\\Windows\\"],
        )
        assert ok is True

    def test_check_forbidden_path_etc_rejected(self):
        ok, reason = risk_rules.check_forbidden_path(
            "/etc/passwd",
            ["/etc/", "/root/"],
        )
        assert ok is False
        assert "/etc/" in reason

    def test_check_forbidden_path_windows_rejected(self):
        ok, reason = risk_rules.check_forbidden_path(
            "C:\\Windows\\System32\\config",
            ["C:\\Windows\\"],
        )
        assert ok is False

    def test_check_forbidden_path_backslash_normalized(self):
        # Forward slashes should be checked against backslash prefixes too
        ok, reason = risk_rules.check_forbidden_path(
            "C:/Windows/System32",
            ["C:\\Windows\\"],
        )
        assert ok is False

    def test_check_tool_allowed_not_forbidden(self):
        ok, reason = risk_rules.check_tool_allowed("browser.open", ["shell.run"])
        assert ok is True

    def test_check_tool_allowed_forbidden(self):
        ok, reason = risk_rules.check_tool_allowed("shell.run", ["shell.run"])
        assert ok is False
        assert "forbidden" in reason

    def test_check_risk_level_within_limit(self):
        ok, reason = risk_rules.check_risk_level("low", "high")
        assert ok is True

    def test_check_risk_level_exceeds_limit(self):
        ok, reason = risk_rules.check_risk_level("critical", "high")
        assert ok is False
        assert "exceeds" in reason

    def test_check_path_in_workspace_absolute_outside(self):
        ok, reason = risk_rules.check_path_in_workspace("/etc/passwd", "/home/user/workspace")
        assert ok is False

    def test_check_path_in_workspace_relative_ok(self):
        ok, reason = risk_rules.check_path_in_workspace("output.txt", "/home/user/workspace")
        assert ok is True

    def test_check_path_in_workspace_inside_workspace(self):
        ok, reason = risk_rules.check_path_in_workspace("/home/user/workspace/file.txt", "/home/user/workspace")
        assert ok is True

    def test_check_args_hash_match(self):
        args = {"key": "value"}
        import hashlib
        expected = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        ok, reason = risk_rules.check_args_hash(args, expected)
        assert ok is True

    def test_check_args_hash_mismatch(self):
        ok, reason = risk_rules.check_args_hash({"key": "value"}, "wronghash12345678")
        assert ok is False
        assert "mismatch" in reason


# ── TokenIssuer tests ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestTokenIssuer:
    def _make_issuer(self, secret="test-secret-key", expire_minutes=5):
        return TokenIssuer(secret, expire_minutes=expire_minutes)

    def test_issue_returns_token_string(self):
        issuer = self._make_issuer()
        token = issuer.issue("task-1", "step-1", "browser.open", {"url": "https://example.com"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_round_trip(self):
        issuer = self._make_issuer()
        args = {"url": "https://example.com"}
        token = issuer.issue("task-1", "step-1", "browser.open", args)

        valid, reason = issuer.verify(token, "task-1", "step-1", "browser.open", args)
        assert valid is True
        assert reason == "OK"

    def test_verify_wrong_task_id(self):
        issuer = self._make_issuer()
        args = {"url": "https://example.com"}
        token = issuer.issue("task-1", "step-1", "browser.open", args)

        valid, reason = issuer.verify(token, "task-2", "step-1", "browser.open", args)
        assert valid is False
        assert "task_id" in reason

    def test_verify_wrong_step_id(self):
        issuer = self._make_issuer()
        args = {"url": "https://example.com"}
        token = issuer.issue("task-1", "step-1", "browser.open", args)

        valid, reason = issuer.verify(token, "task-1", "step-2", "browser.open", args)
        assert valid is False
        assert "step_id" in reason

    def test_verify_wrong_tool_name(self):
        issuer = self._make_issuer()
        args = {"url": "https://example.com"}
        token = issuer.issue("task-1", "step-1", "browser.open", args)

        valid, reason = issuer.verify(token, "task-1", "step-1", "shell.run", args)
        assert valid is False
        assert "tool_name" in reason

    def test_verify_wrong_args(self):
        issuer = self._make_issuer()
        token = issuer.issue("task-1", "step-1", "browser.open", {"url": "https://example.com"})

        valid, reason = issuer.verify(token, "task-1", "step-1", "browser.open", {"url": "https://evil.com"})
        assert valid is False
        assert "args_hash" in reason

    def test_verify_expired_token(self):
        issuer = self._make_issuer(expire_minutes=1)
        args = {"url": "https://example.com"}
        token = issuer.issue("task-1", "step-1", "browser.open", args)

        # Mock time to be past expiry
        with patch("packages.policy.capability_token.time.time", return_value=time.time() + 120):
            valid, reason = issuer.verify(token, "task-1", "step-1", "browser.open", args)
            assert valid is False
            assert "expired" in reason

    def test_verify_tampered_signature(self):
        issuer1 = TokenIssuer("secret-A")
        issuer2 = TokenIssuer("secret-B")
        args = {"url": "https://example.com"}
        token = issuer1.issue("task-1", "step-1", "browser.open", args)

        # Verify with different secret should fail
        valid, reason = issuer2.verify(token, "task-1", "step-1", "browser.open", args)
        assert valid is False
        assert "tampered" in reason

    def test_verify_invalid_token_format(self):
        issuer = self._make_issuer()
        valid, reason = issuer.verify("not-a-valid-token", "task-1", "step-1", "browser.open", {})
        assert valid is False
        assert "Invalid token format" in reason

    def test_verify_missing_signature(self):
        issuer = self._make_issuer()
        # Create a token payload without signature
        payload = json.dumps({"task_id": "t", "step_id": "s", "tool_name": "x", "args_hash": "h"})
        import base64
        bad_token = base64.urlsafe_b64encode(payload.encode()).decode()

        valid, reason = issuer.verify(bad_token, "t", "s", "x", {})
        assert valid is False
        assert "signature" in reason

    def test_compute_args_hash_deterministic(self):
        issuer = self._make_issuer()
        args = {"key": "value", "nested": {"a": 1}}
        h1 = issuer.compute_args_hash(args)
        h2 = issuer.compute_args_hash(args)
        assert h1 == h2

    def test_compute_args_hash_key_order_independent(self):
        issuer = self._make_issuer()
        h1 = issuer.compute_args_hash({"a": 1, "b": 2})
        h2 = issuer.compute_args_hash({"b": 2, "a": 1})
        assert h1 == h2


# ── PolicyEngine tests ─────────────────────────────────────────────────────


@pytest.fixture
def policy_engine():
    """Create a PolicyEngine with real tool registry and test token issuer."""
    registry = ToolRegistry(config_path="configs/tools.yaml")
    issuer = TokenIssuer("test-secret")
    engine = PolicyEngine(registry, issuer, config_path="configs/policy.yaml")
    return engine


@pytest.mark.unit
class TestPolicyEngine:
    def test_allows_safe_browser_open(self, policy_engine):
        result = policy_engine.check("task-1", "step-1", "browser.open", {"url": "https://example.com"})
        assert result.allowed is True
        assert result.risk_level == "low"
        assert result.token is not None

    def test_rejects_shell_run_disabled(self, policy_engine):
        result = policy_engine.check("task-1", "step-1", "shell.run", {"command": "rm -rf /"})
        assert result.allowed is False
        assert "disabled" in result.reason

    def test_rejects_forbidden_tool(self, policy_engine):
        # shell.run is both disabled AND in forbidden_tools
        # desktop.control is disabled AND in forbidden_tools
        result = policy_engine.check("task-1", "step-1", "desktop.control", {})
        assert result.allowed is False

    def test_rejects_localhost_url(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "browser.open", {"url": "http://localhost:8080/api"}
        )
        assert result.allowed is False
        assert "forbidden" in result.reason.lower() or "URL" in result.reason

    def test_rejects_127_url(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "browser.open", {"url": "http://127.0.0.1:3000"}
        )
        assert result.allowed is False

    def test_rejects_private_network_url(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "browser.open", {"url": "http://192.168.1.1/admin"}
        )
        assert result.allowed is False

    def test_rejects_forbidden_path_prefix(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "file.write_docx",
            {"output_path": "/etc/passwd", "title": "x", "paragraphs": []},
        )
        assert result.allowed is False
        assert "forbidden prefix" in result.reason

    def test_rejects_windows_forbidden_path(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "file.write_docx",
            {"output_path": "C:\\Windows\\System32\\config", "title": "x", "paragraphs": []},
        )
        assert result.allowed is False

    def test_issues_token_on_approval(self, policy_engine):
        result = policy_engine.check("task-1", "step-1", "browser.open", {"url": "https://example.com"})
        assert result.token is not None

        # Verify the token
        valid, reason = policy_engine.token_issuer.verify(
            result.token, "task-1", "step-1", "browser.open", {"url": "https://example.com"}
        )
        assert valid is True

    def test_rejects_unregistered_tool(self, policy_engine):
        result = policy_engine.check("task-1", "step-1", "nonexistent.tool", {})
        assert result.allowed is False
        assert "not registered" in result.reason

    def test_low_risk_tool_no_approval_required(self, policy_engine):
        result = policy_engine.check("task-1", "step-1", "browser.open", {"url": "https://example.com"})
        assert result.allowed is True
        assert result.requires_approval is False

    def test_file_tool_with_safe_path_allowed(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "file.write_docx",
            {"output_path": "report.docx", "title": "Report", "paragraphs": ["Hello"]},
        )
        assert result.allowed is True

    def test_personal_tool_rejected_for_enterprise(self, policy_engine):
        # file.search is personal-only
        result = policy_engine.check(
            "task-1", "step-1", "file.search",
            {"keyword": "test"},
            edition="enterprise",
        )
        assert result.allowed is False
        assert "not available for edition" in result.reason

    def test_personal_tool_allowed_for_personal(self, policy_engine):
        result = policy_engine.check(
            "task-1", "step-1", "file.search",
            {"keyword": "test"},
            edition="personal",
        )
        assert result.allowed is True

    def test_policy_result_dataclass(self):
        result = PolicyResult(allowed=True, reason="", risk_level="low")
        assert result.allowed is True
        assert result.token is None
        assert result.requires_approval is False
