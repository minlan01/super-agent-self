"""CLI tool execution — direct tool invocation from the REPL or CLI commands."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from rich.console import Console
from rich.panel import Panel

logger = logging.getLogger(__name__)
console = Console()


def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    edition: str = "personal",
) -> dict[str, Any]:
    """Execute a tool by name with the given arguments.

    This is a simplified execution path for CLI usage that bypasses
    the full task/step/orchestrator pipeline. It performs:
    1. Policy check via the tool's ``check_fn``
    2. Direct ``tool.execute()`` call with a synthetic context

    Returns a dict with ``success``, ``output``, and ``error`` keys.
    """
    from packages.executor.tools.base import ExecutionContext, ToolResult
    from packages.policy.unified_registry import UnifiedToolRegistry

    if tool_name in {"process.execute", "shell.execute"} or tool_name.startswith(
        "terminal."
    ):
        return {
            "success": False,
            "output": None,
            "error": (
                f"Tool '{tool_name}' requires the audited ToolGateway task path; "
                "direct CLI execution is disabled"
            ),
        }

    registry = UnifiedToolRegistry.get_instance()
    reg = registry.get_tool(tool_name)

    if reg is None:
        return {"success": False, "output": None, "error": f"Tool '{tool_name}' not found"}

    # Edition gate
    if reg.edition is not None and edition not in reg.edition:
        return {
            "success": False,
            "output": None,
            "error": f"Tool '{tool_name}' not available in '{edition}' edition",
        }

    if not reg.enabled:
        return {"success": False, "output": None, "error": f"Tool '{tool_name}' is disabled"}

    # Pre-execution safety check
    if reg.check_fn is not None:
        ok, reason = reg.check_fn(args)
        if not ok:
            return {"success": False, "output": None, "error": f"Safety check failed: {reason}"}

    # Get or instantiate the tool
    tool_instance = registry.get_tool_instance(tool_name)
    if tool_instance is None:
        return {
            "success": False, "output": None,
            "error": f"Tool class for '{tool_name}' not available",
        }

    # Build execution context
    from packages.config import get_settings

    try:
        settings = get_settings()
        workspace = settings.workspace_root
    except Exception as e:
        logger.warning("Failed to load workspace_root from config, using default: %s", e)
        workspace = "./workspace"

    context = ExecutionContext(
        task_id=f"cli-{uuid.uuid4().hex[:8]}",
        step_id=f"step-{uuid.uuid4().hex[:8]}",
        edition=edition,
        workspace_root=workspace,
    )

    # Execute
    try:
        result: ToolResult = asyncio.run(tool_instance.execute(args, context))
        return result.to_dict()
    except RuntimeError as e:
        if "Event loop is already running" in str(e):
            return {
                "success": False, "output": None,
                "error": "Cannot run tool: event loop already active",
            }
        return {"success": False, "output": None, "error": str(e)}
    except Exception as e:
        logger.exception("Tool execution failed: %s", tool_name)
        return {"success": False, "output": None, "error": str(e)}


def display_result(result: dict[str, Any], tool_name: str) -> None:
    """Render a tool execution result to the console."""
    if result["success"]:
        output = result.get("output")
        output_str = str(output) if output is not None else "(no output)"
        console.print(Panel(
            output_str[:2000],
            title=f"[green]{tool_name}[/] — Success",
            border_style="green",
        ))
        artifacts = result.get("artifacts", [])
        if artifacts:
            console.print(f"[dim]Artifacts: {', '.join(artifacts)}[/]")
    else:
        error = result.get("error", "Unknown error")
        console.print(Panel(
            error,
            title=f"[red]{tool_name}[/] — Failed",
            border_style="red",
        ))
