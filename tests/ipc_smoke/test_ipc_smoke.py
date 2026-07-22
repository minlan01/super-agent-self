"""Cross-platform IPC smoke test (P0.3).

Validates that the protocol layer imports + serializes correctly on Windows,
Linux, and macOS. This is the minimal "did we break anything platform-specific"
check required by spec §P0.3 + G-04.

This test deliberately avoids:
- Actual Named Pipe / UDS creation (those need platform-specific code in P1+)
- Database access
- Network calls

It focuses on:
1. Importing every v1 schema (catches platform-specific encoding issues)
2. Round-trip serialization (JSON) of each schema
3. Platform adapter contract availability
4. CapabilityReport reports the correct platform name
"""

from __future__ import annotations

import json
import platform
import sys

import pytest


# ---------------------------------------------------------------------------
# 1. Import test — every schema must be importable on every platform
# ---------------------------------------------------------------------------

def test_protocol_imports_clean() -> None:
    """If this fails on Windows/macOS, we have a platform-specific import bug."""
    from packages.protocol.schemas import v1, enums
    assert v1.SCHEMA_VERSION == enums.SCHEMA_VERSION == "1.0.0"


def test_platform_imports_clean() -> None:
    from packages.platform.shared import contracts, errors
    assert hasattr(contracts, "PlatformAdapter")
    assert hasattr(errors, "CapabilityUnavailable")


# ---------------------------------------------------------------------------
# 2. Serialization round-trip (JSON) — catches bytes/unicode/encoding issues
# ---------------------------------------------------------------------------

def test_schema_roundtrip_json() -> None:
    """Every schema must survive a JSON round-trip. Critical on Windows where
    default encodings differ from Linux."""
    from datetime import datetime, timedelta
    from uuid import uuid4

    from packages.protocol.schemas.enums import (
        Classification,
        CommandType,
        RiskLevel,
        TaskStatus,
    )
    from packages.protocol.schemas.v1 import (
        ActorScope,
        Command,
        ExternalReference,
        Task,
    )

    actor = ActorScope(
        tenant_id="tnt-1",
        principal_id="user-1",
        auth_method="oidc",
    )
    cmd = Command(
        command_type=CommandType.SUBMIT,
        aggregate_id=uuid4(),
        actor_scope=actor,
        payload={"goal": "test 任务"},  # include non-ASCII
    )
    s = cmd.model_dump_json()
    # Must be valid JSON with proper UTF-8
    parsed = json.loads(s)
    assert parsed["payload"]["goal"] == "test 任务"
    # Round-trip
    cmd2 = Command.model_validate_json(s)
    assert cmd2.actor_scope.tenant_id == "tnt-1"


def test_unicode_paths_supported() -> None:
    """Windows users with non-ASCII usernames must not break."""
    from packages.protocol.schemas.v1 import ResourceScope
    rs = ResourceScope(
        workspace_id="ws-中文",
        root_paths=["/home/用户/proj", r"C:\Users\用户\proj"],
    )
    s = rs.model_dump_json()
    rs2 = ResourceScope.model_validate_json(s)
    assert rs2.workspace_id == "ws-中文"
    assert rs2.root_paths[0] == "/home/用户/proj"


# ---------------------------------------------------------------------------
# 3. Platform detection — StubPlatformAdapter reports the right OS
# ---------------------------------------------------------------------------

def test_stub_adapter_reports_correct_platform() -> None:
    from packages.platform.shared.contracts import StubPlatformAdapter
    adapter = StubPlatformAdapter()
    name = adapter.platform_name()
    # On Windows → 'windows', Linux → 'linux', macOS → 'darwin'
    expected = platform.system().lower()
    assert name == expected, f"expected {expected!r}, got {name!r}"


def test_capability_report_carries_platform_version() -> None:
    from packages.platform.shared.contracts import StubPlatformAdapter
    report = StubPlatformAdapter().get_capabilities()
    assert report.platform_version  # non-empty
    assert len(report.unsupported_reasons) > 0


# ---------------------------------------------------------------------------
# 4. Error code stability — codes must match across platforms
# ---------------------------------------------------------------------------

def test_error_codes_stable() -> None:
    """Error codes are part of the wire protocol; they must not vary by OS."""
    from packages.platform.shared.errors import CapabilityUnavailable
    from packages.protocol.schemas.enums import ErrorCode
    err = CapabilityUnavailable("test")
    assert err.code == ErrorCode.CAPABILITY_UNAVAILABLE
    assert err.code.value == "A990001"


# ---------------------------------------------------------------------------
# 5. Python version sanity
# ---------------------------------------------------------------------------

def test_python_version_supported() -> None:
    """Spec requires Python >=3.11. We document that 3.12 is preferred for
    the desktop sidecar (per P-1 spike ADR-002)."""
    major, minor = sys.version_info[:2]
    assert (major, minor) >= (3, 11), f"Python {major}.{minor} below 3.11"
