r"""Workspace path safety — prevents tools from escaping workspace boundaries.

Spec §G-12/G-15: all file/shell tools must validate that their target paths
remain within the authorized workspace root.  This module provides the
canonical path validation logic used by ToolGateway and individual tools.

Threats blocked:
  - Path traversal (../ sequences)
  - Absolute path injection (/etc/passwd, C:\Windows\System32)
  - Symlink escape (symlink pointing outside workspace)
  - Windows junction/reparse point escape
  - UNC path injection (\\server\share)
  - Null byte injection (path\0.exe)
  - Case-insensitive bypass on Windows/Windows

Design:
  - resolve_path() canonicalizes and validates a path against workspace root.
  - check_path() is a boolean wrapper for tools that only need yes/no.
  - Windows junctions are detected via os.lstat reparse point attribute.
  - Symlinks are resolved and checked against workspace boundary.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import structlog

logger = structlog.get_logger()


class PathSafetyError(Exception):
    """Raised when a path escapes the workspace boundary."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Path '{path}' rejected: {reason}")


def _is_windows() -> bool:
    return sys.platform == "win32" or os.name == "nt"


def _normalize_workspace_root(workspace_root: str | Path) -> Path:
    """Resolve workspace root to an absolute, canonical path.

    The workspace root itself must not contain symlinks or junctions —
    we resolve it once at startup to establish the trusted boundary.
    """
    root = Path(workspace_root).resolve()
    if not root.is_dir():
        # For testing/initial setup, resolve parent instead.
        root = root.parent.resolve()
    return root


def resolve_path(
    target: str | Path,
    workspace_root: str | Path,
    *,
    allow_create: bool = False,
    check_symlinks: bool = True,
) -> Path:
    """Validate and resolve a target path against the workspace boundary.

    Args:
        target: The path to validate (may be relative or absolute).
        workspace_root: The trusted workspace boundary.
        allow_create: If True, the path doesn't need to exist yet (for write ops).
        check_symlinks: If True, resolve symlinks and check the real path.

    Returns:
        The canonical, validated absolute Path (guaranteed within workspace).

    Raises:
        PathSafetyError: If the path escapes the workspace or contains
                         dangerous constructs.
    """
    target_str = str(target)

    # ── Block null bytes ──
    if "\x00" in target_str:
        raise PathSafetyError(target_str, "null byte in path")

    # ── Block UNC paths (Windows network paths) ──
    if target_str.startswith("\\\\") or target_str.startswith("//"):
        raise PathSafetyError(target_str, "UNC/network path not allowed")

    root = _normalize_workspace_root(workspace_root)

    # ── Reject absolute paths outside workspace ──
    # On Windows, PureWindowsPath; on Linux, PurePosixPath.
    if _is_windows():
        pure_target = PureWindowsPath(target_str)
    else:
        pure_target = PurePosixPath(target_str)

    if pure_target.is_absolute():
        # Check if it starts with the workspace root.
        target_abs = Path(target_str)
        if not _is_within_root(target_abs, root):
            raise PathSafetyError(
                target_str,
                f"absolute path outside workspace root {root}",
            )
    else:
        # Relative path: join with workspace root.
        target_abs = root / target_str

    # ── Canonicalize (resolve .. and .) ──
    # Use os.path.realpath to resolve symlinks AND .. sequences.
    if check_symlinks:
        resolved = Path(os.path.realpath(str(target_abs), strict=False))
    else:
        # Only resolve .. without following symlinks.
        resolved = Path(os.path.normpath(str(target_abs)))

    # ── Check the canonical path is within workspace ──
    if not _is_within_root(resolved, root):
        raise PathSafetyError(
            target_str,
            f"resolved path {resolved} escapes workspace root {root}",
        )

    # ── Symlink/junction escape check ──
    # Even if the path itself is within workspace, a symlink component
    # in the path might point outside. We check each parent directory.
    if check_symlinks and not allow_create:
        _check_symlink_escape(resolved, root)

    # ── Windows junction check ──
    if _is_windows() and resolved.exists():
        _check_windows_junction(resolved, root)

    logger.debug(
        "Path validated: target=%s resolved=%s root=%s",
        target_str, resolved, root,
    )
    return resolved


def check_path(
    target: str | Path,
    workspace_root: str | Path,
    *,
    allow_create: bool = False,
) -> bool:
    """Boolean wrapper around resolve_path(). Returns True if safe."""
    try:
        resolve_path(target, workspace_root, allow_create=allow_create)
        return True
    except PathSafetyError:
        return False


def _is_within_root(path: Path, root: Path) -> bool:
    """Check if *path* is *root* or a descendant of *root*.

    Uses string prefix comparison on canonical paths to handle case
    sensitivity correctly across platforms.
    """
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _check_symlink_escape(path: Path, root: Path) -> None:
    """Check that no component of *path* is a symlink pointing outside root.

    Walks from root downward through each path component, checking if any
    intermediate directory is a symlink whose target escapes workspace.
    """
    root_resolved = root.resolve()
    current = root_resolved

    # Get the relative path components from root to target.
    try:
        rel = path.resolve().relative_to(root_resolved)
    except ValueError:
        # Path is outside root — already caught by main check.
        return

    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            link_target = Path(os.readlink(str(current)))
            if not link_target.is_absolute():
                link_target = (current.parent / link_target).resolve()
            else:
                link_target = link_target.resolve()
            if not _is_within_root(link_target, root_resolved):
                raise PathSafetyError(
                    str(path),
                    f"symlink at {current} points outside workspace "
                    f"(target: {link_target})",
                )


def _check_windows_junction(path: Path, root: Path) -> None:
    """Check for Windows junction/reparse points that escape workspace.

    On Windows, junctions are a special type of reparse point that act
    like directory symlinks but aren't detected by os.path.islink().
    We check the FILE_ATTRIBUTE_REPARSE_POINT flag via os.lstat.
    """
    if not _is_windows():
        return

    try:
        stat = os.lstat(str(path))
        # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        if stat.st_file_attributes & 0x400:  # type: ignore[attr-defined]
            # It's a reparse point — resolve it.
            resolved = Path(os.path.realpath(str(path)))
            if not _is_within_root(resolved, root):
                raise PathSafetyError(
                    str(path),
                    f"Windows junction/reparse point at {path} "
                    f"resolves outside workspace (target: {resolved})",
                )
    except (OSError, AttributeError):
        # On Linux or if lstat fails, skip junction check.
        pass


def sanitize_path_for_display(path: str | Path) -> str:
    """Sanitize a path for logging/display (truncate, no secrets).

    This does NOT validate the path — it's only for safe logging.
    """
    s = str(path)
    if len(s) > 200:
        s = s[:197] + "..."
    return s.replace("\x00", "\\x00")
