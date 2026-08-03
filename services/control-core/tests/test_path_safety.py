"""Tests for workspace path safety (P3.3) — traversal, symlink, junction."""

import os
import tempfile

import pytest

from packages.security.path_safety import (
    PathSafetyError,
    check_path,
    resolve_path,
    sanitize_path_for_display,
)


@pytest.fixture()
def workspace():
    """Create a temp workspace dir with subdirs and a test file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = os.path.join(tmpdir, "workspace")
        os.makedirs(os.path.join(root, "subdir", "nested"))
        os.makedirs(os.path.join(root, "data"))
        with open(os.path.join(root, "data", "file.txt"), "w") as f:
            f.write("test content")
        with open(os.path.join(root, "data", "secret.key"), "w") as f:
            f.write("secret")
        yield root


class TestPathSafety:
    def test_valid_relative_path(self, workspace):
        """A relative path within workspace resolves correctly."""
        resolved = resolve_path("data/file.txt", workspace)
        assert "workspace" in str(resolved)
        assert resolved.exists()

    def test_valid_nested_relative_path(self, workspace):
        resolved = resolve_path("subdir/nested", workspace)
        assert resolved.is_dir()

    def test_absolute_path_within_workspace(self, workspace):
        """Absolute path that IS within workspace root is allowed."""
        abs_path = os.path.join(workspace, "data", "file.txt")
        resolved = resolve_path(abs_path, workspace)
        assert resolved.exists()

    def test_path_traversal_blocked(self, workspace):
        """../../../etc/passwd must be rejected."""
        with pytest.raises(PathSafetyError, match="escapes workspace"):
            resolve_path("../../../etc/passwd", workspace)

    def test_path_traversal_with_valid_prefix_blocked(self, workspace):
        """data/../../../etc/passwd must be rejected even if prefix is valid."""
        with pytest.raises(PathSafetyError, match="escapes workspace"):
            resolve_path("data/../../../etc/passwd", workspace)

    def test_absolute_path_outside_workspace_blocked(self, workspace):
        """/etc/passwd or C:\\Windows must be rejected."""
        with pytest.raises(PathSafetyError, match="outside workspace"):
            resolve_path("/etc/passwd", workspace)

    def test_null_byte_blocked(self, workspace):
        """Null byte injection must be rejected."""
        with pytest.raises(PathSafetyError, match="null byte"):
            resolve_path("data/file.txt\x00.exe", workspace)

    def test_unc_path_blocked(self, workspace):
        """UNC network paths (\\\\server\\share) must be rejected."""
        with pytest.raises(PathSafetyError, match="UNC"):
            resolve_path("\\\\server\\share\\file", workspace)

    def test_double_slash_unc_blocked(self, workspace):
        with pytest.raises(PathSafetyError, match="UNC"):
            resolve_path("//server/share/file", workspace)

    def test_check_path_boolean(self, workspace):
        """check_path returns True for valid, False for invalid."""
        assert check_path("data/file.txt", workspace) is True
        assert check_path("../../etc/passwd", workspace) is False
        assert check_path("/etc/passwd", workspace) is False

    def test_allow_create_nonexistent_path(self, workspace):
        """allow_create=True allows paths that don't exist yet."""
        resolved = resolve_path(
            "data/new_file.txt", workspace, allow_create=True,
        )
        assert "workspace" in str(resolved)

    def test_symlink_escape_blocked(self, workspace):
        """A symlink inside workspace pointing outside must be rejected."""
        # Create a symlink inside workspace pointing to / (outside)
        link_path = os.path.join(workspace, "data", "escape_link")
        os.symlink("/", link_path)

        with pytest.raises(PathSafetyError, match="escapes workspace|symlink.*outside"):
            resolve_path("data/escape_link", workspace)

    def test_symlink_within_workspace_allowed(self, workspace):
        """A symlink inside workspace pointing within workspace is OK."""
        # Create a symlink: data/link -> ../data/file.txt (within workspace)
        link_path = os.path.join(workspace, "data", "internal_link")
        target = os.path.join(workspace, "data", "file.txt")
        os.symlink(target, link_path)

        resolved = resolve_path("data/internal_link", workspace)
        assert resolved.exists()

    def test_dot_dot_in_middle_resolved(self, workspace):
        """data/../data/file.txt resolves to valid path."""
        resolved = resolve_path("data/../data/file.txt", workspace)
        assert resolved.exists()

    def test_workspace_root_itself_valid(self, workspace):
        """The workspace root itself should be valid."""
        resolved = resolve_path(".", workspace)
        assert resolved.is_dir()

    def test_sanitize_for_display(self):
        """sanitize_path_for_display truncates and removes null bytes."""
        long_path = "a" * 300
        result = sanitize_path_for_display(long_path)
        assert len(result) <= 200
        assert result.endswith("...")

        null_path = "file\x00.txt"
        result = sanitize_path_for_display(null_path)
        assert "\x00" not in result

    def test_file_in_root_allowed(self, workspace):
        """A file directly in workspace root is allowed."""
        with open(os.path.join(workspace, "root_file.txt"), "w") as f:
            f.write("root")
        resolved = resolve_path("root_file.txt", workspace)
        assert resolved.exists()

    def test_case_sensitivity_not_bypassed(self, workspace):
        """On case-sensitive filesystems, wrong case shouldn't match.
        On macOS/Windows (case-insensitive), this test is lenient.
        """
        # This is a best-effort test — the key point is that the resolved
        # path must still be within workspace root.
        try:
            resolved = resolve_path("DATA/FILE.TXT", workspace)
            assert "workspace" in str(resolved)
        except PathSafetyError:
            # On case-sensitive FS, DATA/ doesn't exist -> normpath still
            # produces a path within workspace, so this shouldn't fail.
            # If it does, it's acceptable (conservative).
            pass
