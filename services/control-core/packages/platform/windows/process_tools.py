"""P3.10A: Versioned parameterized process execution API.

This module defines the contract for process.execute — a structured,
versioned API that NEVER launches CMD, PowerShell, Bash, or any other
shell interpreter. The executable must be a direct binary path, and
all arguments are passed as separate argv items (no string splitting).

Security invariants:
- executable must be an absolute path to a real file
- cwd must resolve inside the task workspace
- env is filtered through the isolation broker
- No shell interpreters allowed (reject cmd.exe, powershell.exe, bash, sh)
- All fields are runtime-validated types
"""

from __future__ import annotations

import ntpath
import os
import sys as _sys
from dataclasses import dataclass
from typing import Any

from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
from packages.platform.shared.errors import SandboxUnavailable
from packages.policy.unified_registry import tool_registry


def sys_platform() -> str:
    """Return the current platform (test-seamable)."""
    return _sys.platform

# Shell interpreters that must NEVER be launched via process.execute
SHELL_INTERPRETERS: frozenset[str] = frozenset({
    "cmd.exe", "cmd",
    "powershell.exe", "powershell",
    "pwsh.exe", "pwsh",
    "bash", "sh", "zsh", "fish",
    "python.exe", "python", "python3",
    "node.exe", "node",
    "ruby", "perl",
})

# API version
PROCESS_EXECUTE_VERSION = "1.0"


@dataclass(slots=True, frozen=True)
class ProcessExecuteRequest:
    """Versioned process.execute request — never starts shell interpreters.

    Version 1.0:
    - executable: absolute path to a binary (validated, no interpreters)
    - args: list of string arguments (no shell splitting)
    - cwd: working directory (must be inside task workspace)
    - env: optional environment variables (merged with filtered host env)
    - timeout_sec: execution timeout (capped by sandbox profile)
    """

    executable: str
    args: tuple[str, ...]
    cwd: str
    env: dict[str, str] | None = None
    timeout_sec: float = 30.0
    version: str = PROCESS_EXECUTE_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessExecuteRequest:
        """Create from API dict, validating all fields."""
        executable = data.get("executable")
        if not isinstance(executable, str) or not executable:
            raise ValueError("executable must be a non-empty string")

        raw_args = data.get("args", [])
        if not isinstance(raw_args, list):
            raise TypeError("args must be a list")
        for arg in raw_args:
            if not isinstance(arg, str):
                raise TypeError(f"all args must be strings, got {type(arg).__name__}")
        args = tuple(raw_args)

        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("cwd must be a non-empty string")

        env = data.get("env")
        if env is not None:
            if not isinstance(env, dict):
                raise TypeError("env must be a dict or null")
            for k, v in env.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise TypeError("env keys and values must be strings")

        timeout = data.get("timeout_sec", 30.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout_sec must be a number")
        if timeout <= 0:
            raise ValueError("timeout_sec must be positive")

        version = data.get("version", PROCESS_EXECUTE_VERSION)
        if version != PROCESS_EXECUTE_VERSION:
            raise ValueError(
                f"unsupported API version: {version} (expected {PROCESS_EXECUTE_VERSION})"
            )

        return cls(
            executable=executable,
            args=args,
            cwd=cwd,
            env=env,
            timeout_sec=float(timeout),
            version=version,
        )

    def validate_security(self, workspace_root: str) -> None:
        """Validate security constraints before execution.

        - executable must be absolute and not a shell interpreter
        - cwd must resolve inside workspace_root

        Uses ntpath semantics so validation is identical on Windows and on
        cross-platform CI (this is the windows platform module; paths are
        always Windows-style).
        """
        # Check executable
        norm_exec = ntpath.normcase(ntpath.abspath(self.executable))
        exec_name = ntpath.basename(norm_exec).lower()
        if exec_name in SHELL_INTERPRETERS:
            raise SandboxUnavailable(
                f"process.execute refuses to launch shell interpreter: {exec_name}; "
                "use shell.execute (high-risk) if interpreter access is required"
            )

        if not ntpath.isabs(self.executable):
            raise SandboxUnavailable(
                f"executable must be an absolute path: {self.executable}"
            )

        # Check cwd is inside workspace (ntpath semantics).
        abs_cwd = ntpath.normcase(ntpath.abspath(self.cwd))
        abs_workspace = ntpath.normcase(ntpath.abspath(workspace_root))
        try:
            cwd_is_inside = (
                ntpath.commonpath((abs_workspace, abs_cwd)) == abs_workspace
            )
        except ValueError:
            cwd_is_inside = False
        if not cwd_is_inside:
            raise SandboxUnavailable(
                f"cwd must be inside workspace: {abs_cwd} not in {abs_workspace}"
            )

        # Filesystem checks only meaningful on a real Windows host.
        if sys_platform() == "win32" and not os.path.isfile(norm_exec):
            raise SandboxUnavailable(f"executable does not exist: {norm_exec}")
        try:
            executable_is_inside = (
                ntpath.commonpath((abs_workspace, norm_exec)) == abs_workspace
            )
        except ValueError:
            executable_is_inside = False
        if not executable_is_inside:
            raise SandboxUnavailable(
                "process.execute executable must be inside the task workspace"
            )


@dataclass(slots=True, frozen=True)
class ProcessExecuteResult:
    """Result of a parameterized process execution."""

    exit_code: int
    stdout: bytes
    stderr: bytes
    timed_out: bool
    truncated: bool
    duration_sec: float


def _process_execute_check_fn(args: dict[str, Any]) -> tuple[bool, str]:
    try:
        ProcessExecuteRequest.from_dict(args)
    except (TypeError, ValueError) as exc:
        return False, str(exc)
    return True, ""


@tool_registry.register(
    category="system",
    risk_level="high",
    check_fn=_process_execute_check_fn,
    params_schema={
        "type": "object",
        "required": ["executable", "cwd"],
        "properties": {
            "executable": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
            "env": {
                "type": ["object", "null"],
                "additionalProperties": {"type": "string"},
            },
            "timeout_sec": {"type": "number", "default": 30},
            "version": {"type": "string", "default": PROCESS_EXECUTE_VERSION},
        },
        "additionalProperties": False,
    },
)
class ProcessExecute(ToolBase):
    """Execute a direct Workspace binary through the Windows sandbox."""

    name = "process.execute"
    description = "Execute a direct binary without a shell interpreter"

    async def execute(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        if os.name != "nt":
            return ToolResult(
                success=False,
                error="process.execute currently requires Windows AppContainer",
            )
        try:
            request = ProcessExecuteRequest.from_dict(args)
            request.validate_security(context.workspace_root)

            from .sandbox_factory import WindowsProcessSandboxFactory

            exit_code, stdout, stderr = await WindowsProcessSandboxFactory.execute(
                workspace_root=context.workspace_root,
                executable=request.executable,
                args=request.args,
                cwd=request.cwd,
                env=request.env,
                timeout_sec=request.timeout_sec,
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to execute: {exc}")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        return ToolResult(
            success=exit_code == 0,
            output={
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": exit_code,
                "version": request.version,
            },
            error=stderr_text if exit_code != 0 else None,
        )


__all__ = [
    "PROCESS_EXECUTE_VERSION",
    "SHELL_INTERPRETERS",
    "ProcessExecuteRequest",
    "ProcessExecuteResult",
    "ProcessExecute",
]
