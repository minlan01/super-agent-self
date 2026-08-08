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

import os
from dataclasses import dataclass
from typing import Any

from packages.platform.shared.errors import SandboxUnavailable

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
        """
        # Check executable
        abs_exec = os.path.abspath(self.executable)
        exec_name = os.path.basename(abs_exec).lower()
        if exec_name in SHELL_INTERPRETERS:
            raise SandboxUnavailable(
                f"process.execute refuses to launch shell interpreter: {exec_name}; "
                "use shell.execute (high-risk) if interpreter access is required"
            )

        if not os.path.isabs(self.executable):
            raise SandboxUnavailable(
                f"executable must be an absolute path: {self.executable}"
            )

        # Check cwd is inside workspace
        abs_cwd = os.path.abspath(self.cwd)
        abs_workspace = os.path.abspath(workspace_root)
        if not abs_cwd.startswith(abs_workspace):
            raise SandboxUnavailable(
                f"cwd must be inside workspace: {abs_cwd} not in {abs_workspace}"
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


__all__ = [
    "PROCESS_EXECUTE_VERSION",
    "SHELL_INTERPRETERS",
    "ProcessExecuteRequest",
    "ProcessExecuteResult",
]
