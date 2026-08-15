"""Unit tests for the ToolGateway-facing P3.10B terminal adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.personal_shell.executor import execute_tool
from packages.db.models import Base, EffectClassDB, ReceiptStatusDB
from packages.db.session import Base as AppBase
from packages.execution.effect_journal import EffectJournal
from packages.execution.lease_manager import LeaseManager
from packages.executor.tool_gateway import ToolGateway
from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.delegate_tool import BLOCKED_TOOLS
from packages.platform.shared.terminal import (
    TerminalMessage,
    TerminalMessageType,
    TerminalReadResult,
    TerminalSession,
    TerminalSessionState,
)
from packages.platform.windows import terminal_tools
from packages.platform.windows.terminal_tools import (
    TERMINAL_TOOL_NAMES,
    TerminalOpen,
    TerminalRead,
    TerminalWrite,
)
from packages.policy.grant_issuer import GrantIssuer
from packages.policy.unified_registry import tool_registry


class _FakeManager:
    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def default_shell_executable(self) -> str:
        return self.executable

    @staticmethod
    def _session(owner: str, workspace_id: str, executable: str) -> TerminalSession:
        return TerminalSession(
            session_id="session-1",
            owner_principal_id=owner,
            workspace_id=workspace_id,
            executable=executable,
            args=("/d", "/q"),
            state=TerminalSessionState.RUNNING,
        )

    async def open(self, spec, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("open", {"spec": spec, **kwargs}))
        return self._session(
            kwargs["owner_principal_id"],
            kwargs["workspace_id"],
            spec.executable,
        )

    async def write(self, session_id, data, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            ("write", {"session_id": session_id, "data": data, **kwargs})
        )
        return self._session(
            kwargs["owner_principal_id"],
            kwargs["workspace_id"],
            self.executable,
        )

    async def read(self, session_id, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("read", {"session_id": session_id, **kwargs}))
        session = self._session(
            kwargs["owner_principal_id"],
            kwargs["workspace_id"],
            self.executable,
        )
        return TerminalReadResult(
            session=session,
            messages=(
                TerminalMessage(
                    message_type=TerminalMessageType.OUTPUT,
                    payload="中文".encode(),
                    sequence=4,
                ),
            ),
            next_sequence=4,
        )


def _context(tmp_path: Path) -> ExecutionContext:
    return ExecutionContext(
        task_id="task-1",
        step_id="step-1",
        principal_id="principal-1",
        workspace_id="workspace-1",
        workspace_root=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_terminal_open_derives_scope_from_execution_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "cmd.exe"
    executable.write_bytes(b"test")
    fake = _FakeManager(str(executable))
    monkeypatch.setattr(terminal_tools, "_manager", lambda: fake)

    result = await TerminalOpen().execute(
        {"args": ["/d", "/q"]},
        _context(tmp_path),
    )

    assert result.success is True
    call_name, call = fake.calls[0]
    assert call_name == "open"
    assert call["owner_principal_id"] == "principal-1"
    assert call["workspace_id"] == "workspace-1"
    assert call["workspace_root"] == str(tmp_path)
    assert result.output["session"]["owner_principal_id"] == "principal-1"


@pytest.mark.asyncio
async def test_terminal_tools_reject_client_supplied_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "cmd.exe"
    executable.write_bytes(b"test")
    fake = _FakeManager(str(executable))
    monkeypatch.setattr(terminal_tools, "_manager", lambda: fake)

    result = await TerminalWrite().execute(
        {
            "session_id": "session-1",
            "data": "whoami\r\n",
            "owner_principal_id": "attacker",
        },
        _context(tmp_path),
    )

    assert result.success is False
    assert "server-bound" in (result.error or "")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_terminal_read_serializes_utf8_and_base64(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "cmd.exe"
    executable.write_bytes(b"test")
    fake = _FakeManager(str(executable))
    monkeypatch.setattr(terminal_tools, "_manager", lambda: fake)

    result = await TerminalRead().execute(
        {"session_id": "session-1", "after_sequence": 3},
        _context(tmp_path),
    )

    assert result.success is True
    assert result.output["messages"][0]["data"] == "中文"
    assert result.output["messages"][0]["data_base64"] == "5Lit5paH"
    assert result.output["next_sequence"] == 4


def test_all_terminal_tools_are_registered_and_gateway_only() -> None:
    assert TERMINAL_TOOL_NAMES.issubset(BLOCKED_TOOLS)
    for name in TERMINAL_TOOL_NAMES:
        registration = tool_registry.get_tool(name)
        assert registration is not None
        assert registration.params_schema is not None
        properties = registration.params_schema.get("properties", {})
        assert not {"owner_principal_id", "workspace_id"}.intersection(properties)


def test_personal_shell_rejects_terminal_direct_execution() -> None:
    for name in TERMINAL_TOOL_NAMES:
        result = execute_tool(name, {})
        assert result["success"] is False
        assert "audited ToolGateway" in result["error"]


@pytest.mark.asyncio
async def test_terminal_open_executes_through_tool_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "cmd.exe"
    executable.write_bytes(b"test")
    fake = _FakeManager(str(executable))
    monkeypatch.setattr(terminal_tools, "_manager", lambda: fake)
    tool = TerminalOpen()

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    db = Session(engine)
    try:
        grants = GrantIssuer(db)
        leases = LeaseManager(db)
        gateway = ToolGateway(
            db=db,
            grant_issuer=grants,
            lease_manager=leases,
            effect_journal=EffectJournal(db),
            tool_lookup={"terminal.open": tool},
            worker_id="terminal-test-worker",
        )
        issued = grants.issue(
            tenant_id="tenant-1",
            step_run_id="step-1",
            tool_name="terminal.open",
            bound_args_hash="a" * 64,
            risk_level="high",
            resource_scope={"workspace_id": "workspace-1"},
            security_context_digest="b" * 64,
            approval_resolution_id="approval-1",
        )
        lease = leases.acquire(
            tenant_id="tenant-1",
            worker_id="worker-1",
            step_run_id="step-1",
        )

        result = await gateway.invoke(
            handle=issued.handle,
            lease_id=lease.lease_id,
            tool_name="terminal.open",
            args={"args": ["/d", "/q"]},
            context=_context(tmp_path),
            effect_class=EffectClassDB.NON_RETRYABLE,
            tenant_id="tenant-1",
            security_context_digest="b" * 64,
        )

        assert result.success is True
        assert result.receipt_status is ReceiptStatusDB.SUCCEEDED
        assert result.tool_result is not None
        assert result.tool_result.output["session"]["workspace_id"] == "workspace-1"
        assert fake.calls[0][0] == "open"
    finally:
        db.close()
