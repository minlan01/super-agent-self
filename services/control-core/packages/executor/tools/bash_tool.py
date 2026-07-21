"""Bash execute tool — sandboxed shell command execution."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from packages.policy.command_safety import CommandSafetyChecker
from packages.policy.unified_registry import tool_registry

from .base import ExecutionContext, ToolBase, ToolResult

logger = logging.getLogger(__name__)

MAX_TIMEOUT = 120
DEFAULT_TIMEOUT = 30
MAX_OUTPUT_BYTES = 100_000  # 100 KB

# Use the authoritative safety checker from command_safety.py
_safety_checker = CommandSafetyChecker()


def _is_dangerous(command: str) -> tuple[bool, str]:
    """Check if a command matches dangerous patterns. Returns (dangerous, reason)."""
    safe, reason = _safety_checker.check_all(command)
    return not safe, reason


def _is_path_allowed(workdir: str, workspace_root: str) -> bool:
    """Ensure workdir is within workspace_root."""
    try:
        wd = Path(workdir).resolve()
        ws = Path(workspace_root).resolve()
        return wd.is_relative_to(ws)
    except OSError:
        return False


def _bash_check_fn(args: dict) -> tuple[bool, str]:
    """Pre-execution safety check for bash commands."""
    command = args.get("command", "")
    if not command:
        return False, "command is required"
    safe, reason = _safety_checker.check_all(command)
    return safe, reason


@tool_registry.register(
    category="system",
    risk_level="high",
    emoji="💻",
    check_fn=_bash_check_fn,
    params_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (max 120)", "default": 30},
            "workdir": {"type": "string", "description": "Working directory (must be within workspace)"},
        },
        "additionalProperties": False,
    },
)
class BashExecute(ToolBase):
    """Execute a shell command in a sandboxed environment."""

    name = "shell.execute"
    description = "Execute a shell command in sandboxed environment"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        command: str = args.get("command", "").strip()
        if not command:
            return ToolResult(success=False, error="command is required")

        # 1. Check dangerous patterns
        dangerous, reason = _is_dangerous(command)
        if dangerous:
            logger.warning("Blocked dangerous command: %s — %s", command[:50], reason)
            return ToolResult(success=False, error=f"Command blocked: {reason}")

        # 2. Timeout clamping
        timeout = min(int(args.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)

        # 3. Working directory restriction
        workspace_root = context.workspace_root
        workdir = args.get("workdir", workspace_root)
        if not _is_path_allowed(workdir, workspace_root):
            return ToolResult(
                success=False,
                error=f"Workdir '{workdir}' is outside workspace '{workspace_root}'",
            )

        # 4. Execute
        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            if proc is not None:
                proc.kill()
                await proc.wait()
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout}s",
            )
        except Exception as exc:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.debug("Failed to kill process on error", exc_info=True)
            return ToolResult(success=False, error=f"Failed to execute: {exc}")

        # 5. Truncate output if too large
        stdout = stdout_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        stderr = stderr_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else -1

        return ToolResult(
            success=(exit_code == 0),
            output={
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
            },
            error=stderr if exit_code != 0 else None,
        )
