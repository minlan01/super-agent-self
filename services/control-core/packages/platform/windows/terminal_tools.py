"""Registered ToolGateway adapters for P3.10B terminal sessions."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
from packages.platform.shared.errors import PermissionDenied
from packages.platform.shared.terminal import (
    TERMINAL_PROTOCOL_VERSION,
    TerminalOpenSpec,
    TerminalReadResult,
    TerminalSession,
    TerminalSignal,
)
from packages.policy.unified_registry import tool_registry

from .conpty import WindowsConPTYManager, get_default_conpty_manager

_FORBIDDEN_SCOPE_FIELDS = frozenset(
    {"owner", "owner_principal_id", "principal_id", "workspace_id", "workspace_root"}
)


def _manager() -> WindowsConPTYManager:
    return get_default_conpty_manager()


def _scope(context: ExecutionContext) -> tuple[str, str]:
    workspace = os.path.normcase(os.path.realpath(os.path.abspath(context.workspace_root)))
    owner = context.principal_id or f"task:{context.task_id}"
    workspace_id = context.workspace_id or f"path:{workspace}"
    return owner, workspace_id


def _reject_client_scope(args: dict[str, Any]) -> None:
    supplied = sorted(_FORBIDDEN_SCOPE_FIELDS.intersection(args))
    if supplied:
        raise PermissionDenied(
            "terminal owner/workspace scope is server-bound; forbidden fields: "
            + ", ".join(supplied)
        )


def _session_payload(session: TerminalSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "owner_principal_id": session.owner_principal_id,
        "workspace_id": session.workspace_id,
        "executable": session.executable,
        "args": list(session.args),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "state": session.state.value,
        "exit_code": session.exit_code,
        "cols": session.cols,
        "rows": session.rows,
        "output_truncated": session.output_truncated,
        "resource_limits": dict(session.resource_limits),
        "protocol_version": session.protocol_version,
    }


def _read_payload(result: TerminalReadResult) -> dict[str, Any]:
    messages = []
    for message in result.messages:
        messages.append(
            {
                "type": message.message_type.value,
                "sequence": message.sequence,
                "timestamp": message.timestamp,
                "data": message.payload.decode("utf-8", errors="replace"),
                "data_base64": base64.b64encode(message.payload).decode("ascii"),
            }
        )
    return {
        "session": _session_payload(result.session),
        "messages": messages,
        "next_sequence": result.next_sequence,
    }


def _session_check(args: dict[str, Any]) -> tuple[bool, str]:
    if _FORBIDDEN_SCOPE_FIELDS.intersection(args):
        return False, "terminal owner/workspace scope is server-bound"
    session_id = args.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return False, "session_id is required"
    return True, ""


def _open_check(args: dict[str, Any]) -> tuple[bool, str]:
    if _FORBIDDEN_SCOPE_FIELDS.intersection(args):
        return False, "terminal owner/workspace scope is server-bound"
    version = args.get("protocol_version", TERMINAL_PROTOCOL_VERSION)
    if version != TERMINAL_PROTOCOL_VERSION:
        return False, f"unsupported terminal protocol version: {version}"
    return True, ""


def _resolve_open_spec(
    args: dict[str, Any],
    context: ExecutionContext,
    manager: WindowsConPTYManager,
) -> TerminalOpenSpec:
    workspace = Path(context.workspace_root).resolve(strict=True)
    executable_value = args.get("executable")
    if executable_value is None:
        executable = Path(manager.default_shell_executable())
    elif not isinstance(executable_value, str) or not executable_value:
        raise ValueError("executable must be a non-empty string")
    else:
        executable = Path(executable_value)
        if not executable.is_absolute():
            executable = workspace / executable

    cwd_value = args.get("cwd")
    if cwd_value is None:
        cwd = workspace
    elif not isinstance(cwd_value, str) or not cwd_value:
        raise ValueError("cwd must be a non-empty string")
    else:
        cwd = Path(cwd_value)
        if not cwd.is_absolute():
            cwd = workspace / cwd

    default_args = ["/d", "/q", "/k"] if executable_value is None else []
    raw_args = args.get("args", default_args)
    if not isinstance(raw_args, list) or any(
        not isinstance(value, str) for value in raw_args
    ):
        raise TypeError("args must be an array of strings")
    raw_env = args.get("env") or {}
    if not isinstance(raw_env, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_env.items()
    ):
        raise TypeError("env must be an object with string values")

    return TerminalOpenSpec(
        executable=str(executable.resolve(strict=True)),
        args=tuple(raw_args),
        cwd=str(cwd.resolve(strict=True)),
        env=tuple(sorted(raw_env.items())),
        cols=int(args.get("cols", 80)),
        rows=int(args.get("rows", 24)),
        timeout_sec=float(args.get("timeout_sec", 300)),
        output_size_limit_mb=int(args.get("output_size_limit_mb", 10)),
        cpu_limit_cores=float(args.get("cpu_limit_cores", 0.5)),
        memory_limit_mb=int(args.get("memory_limit_mb", 256)),
        pids_limit=int(args.get("pids_limit", 10)),
        protocol_version=str(
            args.get("protocol_version", TERMINAL_PROTOCOL_VERSION)
        ),
    )


_OPEN_SCHEMA = {
    "type": "object",
    "properties": {
        "executable": {"type": "string"},
        "args": {"type": "array", "items": {"type": "string"}},
        "cwd": {"type": "string"},
        "env": {
            "type": ["object", "null"],
            "additionalProperties": {"type": "string"},
        },
        "cols": {"type": "integer", "minimum": 1, "maximum": 500},
        "rows": {"type": "integer", "minimum": 1, "maximum": 200},
        "timeout_sec": {"type": "number", "exclusiveMinimum": 0},
        "output_size_limit_mb": {"type": "integer", "minimum": 1},
        "cpu_limit_cores": {"type": "number", "exclusiveMinimum": 0},
        "memory_limit_mb": {"type": "integer", "minimum": 1},
        "pids_limit": {"type": "integer", "minimum": 1},
        "protocol_version": {
            "type": "string",
            "default": TERMINAL_PROTOCOL_VERSION,
        },
    },
    "additionalProperties": False,
}


@tool_registry.register(
    category="system",
    risk_level="high",
    check_fn=_open_check,
    params_schema=_OPEN_SCHEMA,
)
class TerminalOpen(ToolBase):
    name = "terminal.open"
    description = "Open a task-scoped Windows ConPTY session"

    async def execute(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        try:
            _reject_client_scope(args)
            manager = _manager()
            spec = _resolve_open_spec(args, context, manager)
            owner, workspace_id = _scope(context)
            session = await manager.open(
                spec,
                owner_principal_id=owner,
                workspace_id=workspace_id,
                workspace_root=context.workspace_root,
            )
            return ToolResult(success=True, output={"session": _session_payload(session)})
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to open terminal: {exc}")


@tool_registry.register(
    category="system",
    risk_level="high",
    check_fn=_session_check,
    params_schema={
        "type": "object",
        "required": ["session_id", "data"],
        "properties": {
            "session_id": {"type": "string"},
            "data": {"type": "string"},
        },
        "additionalProperties": False,
    },
)
class TerminalWrite(ToolBase):
    name = "terminal.write"
    description = "Write UTF-8 input to a task-scoped terminal session"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        try:
            _reject_client_scope(args)
            data = args.get("data")
            if not isinstance(data, str) or not data:
                raise ValueError("data must be a non-empty string")
            owner, workspace_id = _scope(context)
            session = await _manager().write(
                str(args.get("session_id", "")),
                data.encode("utf-8"),
                owner_principal_id=owner,
                workspace_id=workspace_id,
            )
            return ToolResult(success=True, output={"session": _session_payload(session)})
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to write terminal: {exc}")


@tool_registry.register(
    category="system",
    risk_level="medium",
    check_fn=_session_check,
    params_schema={
        "type": "object",
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "after_sequence": {"type": "integer", "minimum": 0, "default": 0},
            "max_bytes": {"type": "integer", "minimum": 8192, "maximum": 1048576},
            "timeout_sec": {"type": "number", "minimum": 0, "maximum": 30},
        },
        "additionalProperties": False,
    },
)
class TerminalRead(ToolBase):
    name = "terminal.read"
    description = "Read sequenced output from a task-scoped terminal session"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        try:
            _reject_client_scope(args)
            owner, workspace_id = _scope(context)
            result = await _manager().read(
                str(args.get("session_id", "")),
                owner_principal_id=owner,
                workspace_id=workspace_id,
                after_sequence=int(args.get("after_sequence", 0)),
                max_bytes=int(args.get("max_bytes", 64 * 1024)),
                timeout_sec=float(args.get("timeout_sec", 1.0)),
            )
            return ToolResult(success=True, output=_read_payload(result))
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to read terminal: {exc}")


@tool_registry.register(
    category="system",
    risk_level="medium",
    check_fn=_session_check,
    params_schema={
        "type": "object",
        "required": ["session_id", "cols", "rows"],
        "properties": {
            "session_id": {"type": "string"},
            "cols": {"type": "integer", "minimum": 1, "maximum": 500},
            "rows": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "additionalProperties": False,
    },
)
class TerminalResize(ToolBase):
    name = "terminal.resize"
    description = "Resize a task-scoped terminal session"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        try:
            _reject_client_scope(args)
            owner, workspace_id = _scope(context)
            session = await _manager().resize(
                str(args.get("session_id", "")),
                int(args.get("cols", 0)),
                int(args.get("rows", 0)),
                owner_principal_id=owner,
                workspace_id=workspace_id,
            )
            return ToolResult(success=True, output={"session": _session_payload(session)})
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to resize terminal: {exc}")


@tool_registry.register(
    category="system",
    risk_level="high",
    check_fn=_session_check,
    params_schema={
        "type": "object",
        "required": ["session_id", "signal"],
        "properties": {
            "session_id": {"type": "string"},
            "signal": {
                "type": "string",
                "enum": [signal.value for signal in TerminalSignal],
            },
        },
        "additionalProperties": False,
    },
)
class TerminalSendSignal(ToolBase):
    name = "terminal.signal"
    description = "Send Ctrl-C, EOF, or terminate to a task-scoped terminal"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        try:
            _reject_client_scope(args)
            owner, workspace_id = _scope(context)
            session = await _manager().signal(
                str(args.get("session_id", "")),
                TerminalSignal(str(args.get("signal", ""))),
                owner_principal_id=owner,
                workspace_id=workspace_id,
            )
            return ToolResult(success=True, output={"session": _session_payload(session)})
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to signal terminal: {exc}")


class _TerminalSimpleAction(ToolBase):
    action_name = ""

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        try:
            _reject_client_scope(args)
            owner, workspace_id = _scope(context)
            action = getattr(_manager(), self.action_name)
            session = await action(
                str(args.get("session_id", "")),
                owner_principal_id=owner,
                workspace_id=workspace_id,
            )
            return ToolResult(success=True, output={"session": _session_payload(session)})
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to {self.action_name} terminal: {exc}",
            )


_SESSION_ONLY_SCHEMA = {
    "type": "object",
    "required": ["session_id"],
    "properties": {"session_id": {"type": "string"}},
    "additionalProperties": False,
}


@tool_registry.register(
    category="system",
    risk_level="medium",
    check_fn=_session_check,
    params_schema=_SESSION_ONLY_SCHEMA,
)
class TerminalAttach(_TerminalSimpleAction):
    name = "terminal.attach"
    description = "Reattach to a task-scoped terminal session"
    action_name = "attach"


@tool_registry.register(
    category="system",
    risk_level="medium",
    check_fn=_session_check,
    params_schema=_SESSION_ONLY_SCHEMA,
)
class TerminalDisconnect(_TerminalSimpleAction):
    name = "terminal.disconnect"
    description = "Disconnect while preserving the terminal for a short grace period"
    action_name = "disconnect"


@tool_registry.register(
    category="system",
    risk_level="low",
    check_fn=_session_check,
    params_schema=_SESSION_ONLY_SCHEMA,
)
class TerminalHeartbeat(_TerminalSimpleAction):
    name = "terminal.heartbeat"
    description = "Refresh terminal session liveness"
    action_name = "heartbeat"


@tool_registry.register(
    category="system",
    risk_level="high",
    check_fn=_session_check,
    params_schema=_SESSION_ONLY_SCHEMA,
)
class TerminalClose(_TerminalSimpleAction):
    name = "terminal.close"
    description = "Terminate and clean up a task-scoped terminal session"
    action_name = "close"


TERMINAL_TOOL_NAMES = frozenset(
    {
        "terminal.open",
        "terminal.write",
        "terminal.read",
        "terminal.resize",
        "terminal.signal",
        "terminal.attach",
        "terminal.disconnect",
        "terminal.heartbeat",
        "terminal.close",
    }
)


__all__ = [
    "TERMINAL_TOOL_NAMES",
    "TerminalOpen",
    "TerminalWrite",
    "TerminalRead",
    "TerminalResize",
    "TerminalSendSignal",
    "TerminalAttach",
    "TerminalDisconnect",
    "TerminalHeartbeat",
    "TerminalClose",
]
