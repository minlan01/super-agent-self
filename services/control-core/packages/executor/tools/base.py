"""Tool base classes and result types for the Executor."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Standardized result from any tool execution."""

    success: bool
    output: Any = None
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)  # file paths, screenshot paths, etc.
    # Gateway execution metadata.  These fields remain optional so legacy
    # ToolRunner callers and existing tools keep the original contract.
    status: str | None = None
    approval_request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
            "status": self.status,
            "approval_request_id": self.approval_request_id,
        }


class ToolBase(ABC):
    """Abstract base class for all tools.

    Subclasses define class-level metadata that the ``@tool_registry.register()``
    decorator can read as defaults.  The decorator kwargs override these; if
    the decorator omits a kwarg, the class attribute is used as fallback.
    """

    name: str = ""
    description: str = ""
    category: str = ""  # "browser", "file", "system", "web", "agent", "desktop"
    risk_level: str = "low"  # "low" | "medium" | "high" | "critical"
    emoji: str = ""
    params_schema: dict[str, Any] = {}
    check_fn: Any = None  # Optional Callable[[dict], tuple[bool, str]]

    @abstractmethod
    async def execute(self, args: dict[str, Any], context: "ExecutionContext") -> ToolResult:
        """Execute the tool with given args and context."""
        ...


@dataclass
class ExecutionContext:
    """Context passed to every tool execution."""

    task_id: str
    step_id: str
    edition: str = "enterprise"
    workspace_root: str = "./workspace"
    screenshots_dir: str = "screenshots"
    outputs_dir: str = "outputs"
    max_file_size_mb: int = 50
    browser_headless: bool = True
    browser_timeout: int = 30000
    tool_timeout: int = 120
    delegate_depth: int = 0
    principal_id: str | None = None
    workspace_id: str | None = None
    tenant_id: str = "default"
    _browser_context: Any = field(default=None, repr=False)

    @property
    def outputs_path(self) -> str:
        from pathlib import Path
        p = Path(self.workspace_root) / self.outputs_dir
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    @property
    def screenshots_path(self) -> str:
        from pathlib import Path
        p = Path(self.workspace_root) / self.screenshots_dir
        p.mkdir(parents=True, exist_ok=True)
        return str(p)
