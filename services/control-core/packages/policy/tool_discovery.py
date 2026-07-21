"""Tool Discovery — auto-discovers ToolBase subclasses from tool files."""

from __future__ import annotations

import ast
import importlib
import logging
from pathlib import Path
from typing import Any

from packages.executor.tools.base import ToolBase

logger = logging.getLogger(__name__)

# Directory containing tool files
_TOOLS_DIR = Path(__file__).parent.parent / "executor" / "tools"


def discover_tools(tools_dir: Path | str | None = None) -> list[type[ToolBase]]:
    """Scan tool files and auto-discover ToolBase subclasses.

    Uses AST to find class definitions that inherit from ToolBase,
    then imports them dynamically. Skips base.py and __init__.py.

    Returns:
        List of ToolBase subclass types.
    """
    tools_dir = Path(tools_dir) if tools_dir else _TOOLS_DIR
    discovered: list[type[ToolBase]] = []

    if not tools_dir.exists():
        logger.warning("Tools directory not found: %s", tools_dir)
        return discovered

    # Find all Python files except base.py and __init__.py
    tool_files = sorted(
        f for f in tools_dir.glob("*.py")
        if f.name not in ("__init__.py", "base.py")
    )

    for tool_file in tool_files:
        classes = _find_toolbase_subclasses(tool_file)
        for class_name in classes:
            try:
                cls = _import_class(tool_file, class_name)
                if cls is not None:
                    discovered.append(cls)
                    logger.info("Discovered tool: %s from %s", class_name, tool_file.name)
            except Exception as exc:
                logger.warning("Failed to import %s from %s: %s", class_name, tool_file.name, exc)

    return discovered


def _find_toolbase_subclasses(filepath: Path) -> list[str]:
    """Parse a Python file with AST to find classes that inherit from ToolBase."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check bases for ToolBase
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr

            if base_name == "ToolBase":
                results.append(node.name)
                break

    return results


def _import_class(filepath: Path, class_name: str) -> type[ToolBase] | None:
    """Import a class from a file by name."""
    # Convert file path to module path
    # e.g., packages/executor/tools/file_tools.py → packages.executor.tools.file_tools
    parts = filepath.parts

    # Find 'packages' in the path
    try:
        pkg_idx = list(parts).index("packages")
    except ValueError:
        return None

    module_parts = parts[pkg_idx:-1] + (filepath.stem,)
    module_name = ".".join(module_parts)

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)

    if cls is None or not (isinstance(cls, type) and issubclass(cls, ToolBase)):
        return None

    return cls


def register_discovered_tools(tool_runner: Any) -> list[str]:
    """Discover and register all tools into a ToolRunner.

    Returns list of registered tool names.
    """
    tool_classes = discover_tools()
    names = []
    for cls in tool_classes:
        try:
            instance = cls()
            tool_runner.register(instance)
            names.append(instance.name)
        except Exception as exc:
            logger.warning("Failed to instantiate %s: %s", cls.__name__, exc)
    return names
