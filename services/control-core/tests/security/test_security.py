"""Security tests -- token tampering, expiry, mismatches, forbidden tools/paths/URLs."""

import time
from unittest.mock import patch

import pytest

from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.risk_rules import check_forbidden_path, check_tool_allowed, check_url_allowed
from packages.policy.tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_registry():
    return ToolRegistry(config_path="configs/tools.yaml")


@pytest.fixture
def token_issuer():
    return TokenIssuer("security-test-secret", expire_minutes=5)


@pytest.fixture
def policy_engine(tool_registry, token_issuer):
    return PolicyEngine(tool_registry, token_issuer, config_path="configs/policy.yaml")


# ---------------------------------------------------------------------------
# Token tampering detection
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_token_tampered_signature_rejected(token_issuer):
    """Token signed by one issuer must be rejected when verified by another issuer."""
    issuer_a = TokenIssuer("secret-A")
    issuer_b = TokenIssuer("secret-B")
    args = {"url": "https://example.com"}

    token = issuer_a.issue("task-1", "step-1", "browser.open", args)
    valid, reason = issuer_b.verify(token, "task-1", "step-1", "browser.open", args)

    assert valid is False
    assert "tampered" in reason.lower() or "mismatch" in reason.lower()


@pytest.mark.security
def test_token_corrupted_payload_rejected(token_issuer):
    """A token whose base64 payload has been altered mid-stream must be rejected."""
    args = {"url": "https://example.com"}
    token = token_issuer.issue("task-1", "step-1", "browser.open", args)

    # Flip a byte in the base64 payload
    raw_bytes = bytearray(token.encode())
    mid = len(raw_bytes) // 2
    raw_bytes[mid] = (raw_bytes[mid] + 1) % 256
    corrupted = bytes(raw_bytes).decode("ascii", errors="replace")

    valid, reason = token_issuer.verify(
        corrupted, "task-1", "step-1", "browser.open", args
    )
    assert valid is False


# ---------------------------------------------------------------------------
# Token expiry enforcement
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_token_expired_rejected(token_issuer):
    """A token that has passed its expiry window must be rejected."""
    short_issuer = TokenIssuer("short-lived", expire_minutes=1)
    args = {"url": "https://example.com"}
    token = short_issuer.issue("task-1", "step-1", "browser.open", args)

    with patch("packages.policy.capability_token.time.time", return_value=time.time() + 120):
        valid, reason = short_issuer.verify(
            token, "task-1", "step-1", "browser.open", args
        )

    assert valid is False
    assert "expired" in reason.lower()


# ---------------------------------------------------------------------------
# Token task_id mismatch
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_token_task_id_mismatch_rejected(token_issuer):
    """A token issued for task-A must be rejected when presented for task-B."""
    args = {"url": "https://example.com"}
    token = token_issuer.issue("task-A", "step-1", "browser.open", args)

    valid, reason = token_issuer.verify(
        token, "task-B", "step-1", "browser.open", args
    )

    assert valid is False
    assert "task_id" in reason.lower()


# ---------------------------------------------------------------------------
# Token args_hash mismatch
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_token_args_hash_mismatch_rejected(token_issuer):
    """A token issued for one set of args must be rejected when different args are presented."""
    args_original = {"url": "https://example.com"}
    args_tampered = {"url": "https://evil.com"}

    token = token_issuer.issue("task-1", "step-1", "browser.open", args_original)

    valid, reason = token_issuer.verify(
        token, "task-1", "step-1", "browser.open", args_tampered
    )

    assert valid is False
    assert "args_hash" in reason.lower()


# ---------------------------------------------------------------------------
# Tool not registered
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_tool_not_registered_rejected(policy_engine):
    """PolicyEngine must reject a tool that does not exist in the registry."""
    result = policy_engine.check("task-1", "step-1", "nonexistent.tool", {})

    assert result.allowed is False
    assert "not registered" in result.reason.lower()


# ---------------------------------------------------------------------------
# Tool disabled
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_disabled_tool_rejected(policy_engine):
    """PolicyEngine must reject a tool that is registered but disabled."""
    # shell.run is disabled in configs/tools.yaml
    result = policy_engine.check("task-1", "step-1", "shell.run", {"command": "echo hello"})

    assert result.allowed is False
    assert "disabled" in result.reason.lower()


# ---------------------------------------------------------------------------
# Tool forbidden
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_forbidden_tool_rejected(policy_engine):
    """PolicyEngine must reject a tool listed in the forbidden_tools config."""
    # desktop.control is in forbidden_tools and disabled
    result = policy_engine.check("task-1", "step-1", "desktop.control", {})

    assert result.allowed is False


# ---------------------------------------------------------------------------
# Path traversal blocking
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_path_traversal_etc_passwd_blocked():
    """Path traversal via ../../etc/passwd must be caught by the file tool's workspace safety check."""
    from pathlib import Path

    from packages.executor.tools.file_tools import _check_path_within_base

    workspace = Path("/home/user/workspace/outputs")
    malicious = workspace / "../../etc/passwd"

    safe, err = _check_path_within_base(malicious, workspace)
    assert safe is False
    assert "workspace" in err.lower() or "escape" in err.lower()


@pytest.mark.security
def test_forbidden_path_prefixes_blocked(policy_engine):
    """PolicyEngine must block absolute paths that match forbidden_path_prefixes."""
    result = policy_engine.check(
        "task-1", "step-1", "file.write_docx",
        {"output_path": "/etc/passwd", "title": "x", "paragraphs": []},
    )

    assert result.allowed is False
    assert "forbidden" in result.reason.lower() or "prefix" in result.reason.lower()


@pytest.mark.security
def test_path_traversal_root_blocked(policy_engine):
    """PolicyEngine must block file tools that target /root/."""
    result = policy_engine.check(
        "task-1", "step-1", "file.write_docx",
        {"output_path": "/root/.ssh/authorized_keys", "title": "x", "paragraphs": []},
    )

    assert result.allowed is False
    assert "forbidden" in result.reason.lower() or "prefix" in result.reason.lower()


@pytest.mark.security
def test_check_forbidden_path_prefix_etc():
    """risk_rules.check_forbidden_path must reject paths starting with /etc/."""
    ok, reason = check_forbidden_path("/etc/passwd", ["/etc/", "/root/"])
    assert ok is False
    assert "/etc/" in reason


@pytest.mark.security
def test_check_forbidden_path_prefix_windows():
    """risk_rules.check_forbidden_path must reject Windows paths (forward slash normalized)."""
    ok, reason = check_forbidden_path("C:/Windows/System32/config", ["C:\\Windows\\"])
    assert ok is False


# ---------------------------------------------------------------------------
# Forbidden URL blocking
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_forbidden_url_localhost_blocked(policy_engine):
    """PolicyEngine must block browser.open targeting localhost."""
    result = policy_engine.check(
        "task-1", "step-1", "browser.open", {"url": "http://localhost:8080/admin"},
    )

    assert result.allowed is False
    assert "forbidden" in result.reason.lower() or "url" in result.reason.lower()


@pytest.mark.security
def test_forbidden_url_127_blocked(policy_engine):
    """PolicyEngine must block browser.open targeting 127.0.0.1."""
    result = policy_engine.check(
        "task-1", "step-1", "browser.open", {"url": "http://127.0.0.1:3000/api"},
    )

    assert result.allowed is False


@pytest.mark.security
def test_forbidden_url_file_scheme():
    """check_url_allowed should block file:// scheme URLs."""
    # file:// is not in the default patterns, but adding a pattern for it
    ok, reason = check_url_allowed(
        "file:///etc/passwd",
        ["file://"],
    )
    assert ok is False
    assert "forbidden" in reason.lower()


@pytest.mark.security
def test_forbidden_url_private_network(policy_engine):
    """PolicyEngine must block browser.open targeting private network (192.168.x.x)."""
    result = policy_engine.check(
        "task-1", "step-1", "browser.open", {"url": "http://192.168.1.1/admin"},
    )

    assert result.allowed is False


@pytest.mark.security
def test_safe_url_allowed(policy_engine):
    """PolicyEngine must allow browser.open to a safe public URL."""
    result = policy_engine.check(
        "task-1", "step-1", "browser.open", {"url": "https://example.com/page"},
    )

    assert result.allowed is True
    assert result.token is not None


# ---------------------------------------------------------------------------
# Token step_id mismatch (bonus security check)
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_token_step_id_mismatch_rejected(token_issuer):
    """A token issued for step-1 must be rejected when presented for step-2."""
    args = {"url": "https://example.com"}
    token = token_issuer.issue("task-1", "step-1", "browser.open", args)

    valid, reason = token_issuer.verify(
        token, "task-1", "step-2", "browser.open", args
    )

    assert valid is False
    assert "step_id" in reason.lower()


# ---------------------------------------------------------------------------
# Token tool_name mismatch (bonus security check)
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_token_tool_name_mismatch_rejected(token_issuer):
    """A token issued for browser.open must be rejected when presented for shell.run."""
    args = {"url": "https://example.com"}
    token = token_issuer.issue("task-1", "step-1", "browser.open", args)

    valid, reason = token_issuer.verify(
        token, "task-1", "step-1", "shell.run", {"command": "rm -rf /"}
    )

    assert valid is False
    assert "tool_name" in reason.lower()


# ---------------------------------------------------------------------------
# check_tool_allowed standalone
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_check_tool_allowed_rejects_forbidden():
    ok, reason = check_tool_allowed("shell.run", ["shell.run", "desktop.control"])
    assert ok is False
    assert "forbidden" in reason.lower()


@pytest.mark.security
def test_check_tool_allowed_allows_safe():
    ok, reason = check_tool_allowed("file.read", ["shell.run", "desktop.control"])
    assert ok is True
    assert reason == ""
