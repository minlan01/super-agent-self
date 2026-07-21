"""Risk assessment rules for policy checks."""

import hashlib
import json
import re
from typing import Any
from urllib.parse import unquote


def check_tool_allowed(tool_name: str, forbidden_tools: list[str]) -> tuple[bool, str]:
    """Check if a tool is in the forbidden list."""
    if tool_name in forbidden_tools:
        return False, f"Tool '{tool_name}' is forbidden"
    return True, ""


def check_tool_enabled(tool_registry: Any, tool_name: str) -> tuple[bool, str]:
    """Check if a tool is registered and enabled."""
    if not tool_registry.is_registered(tool_name):
        return False, f"Tool '{tool_name}' is not registered"
    if not tool_registry.is_enabled(tool_name):
        return False, f"Tool '{tool_name}' is disabled"
    return True, ""


def check_path_in_workspace(path: str, workspace_root: str) -> tuple[bool, str]:
    """Check if a path stays within the workspace.

    Resolves symlinks and normalizes to prevent traversal attacks like ../../etc/passwd.
    """
    from pathlib import Path

    try:
        workspace = Path(workspace_root).resolve()
        target = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if target.is_relative_to(workspace):
            return True, ""
        return False, f"Path '{path}' resolves outside workspace"
    except (ValueError, OSError) as e:
        return False, f"Invalid path: {e}"


def check_forbidden_path(path: str, forbidden_prefixes: list[str]) -> tuple[bool, str]:
    """Check if a path starts with a forbidden prefix.

    Decodes URL-encoded characters (including double-encoding) and
    normalizes backslashes to forward slashes before matching.
    """
    decoded = unquote(unquote(str(path)))
    normalized = decoded.replace("\\", "/")
    for prefix in forbidden_prefixes:
        prefix_normalized = prefix.replace("\\", "/")
        if normalized.startswith(prefix_normalized):
            return False, f"Path '{path}' matches forbidden prefix '{prefix}'"
    return True, ""


def check_url_allowed(url: str, forbidden_patterns: list[str]) -> tuple[bool, str]:
    """Check if a URL matches any forbidden pattern."""
    for pattern in forbidden_patterns:
        if re.search(pattern, url):
            return False, f"URL '{url}' matches forbidden pattern"
    return True, ""


def check_risk_level(risk_level: str, max_allowed: str) -> tuple[bool, str]:
    """Check if a risk level is within the allowed maximum."""
    levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if levels.get(risk_level, 0) > levels.get(max_allowed, 2):
        return False, f"Risk level '{risk_level}' exceeds maximum allowed '{max_allowed}'"
    return True, ""


def check_args_hash(args: dict, expected_hash: str) -> tuple[bool, str]:
    """Verify args match the expected hash."""
    actual = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
    if actual != expected_hash:
        return False, f"Args hash mismatch: expected {expected_hash}, got {actual}"
    return True, ""
