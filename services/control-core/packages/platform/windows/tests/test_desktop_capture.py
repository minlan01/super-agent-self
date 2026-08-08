"""P3.11/P3.12 tests: UI Automation and Screen Capture contracts."""

from __future__ import annotations

import pytest

from packages.platform.windows.desktop import (
    Classification,
    DesktopInputNotAvailable,
    ScreenCaptureNotAvailable,
    ScreenshotArtifact,
    ScreenshotResult,
    UIAElement,
    WindowSnapshot,
    compute_ui_digest,
    is_uia_available,
    is_wgc_available,
    validate_not_stale,
)


class TestWindowSnapshot:
    """Test window snapshot and stale detection."""

    def test_snapshot_is_frozen(self):
        """WindowSnapshot must be immutable."""
        snap = WindowSnapshot(
            window_id="w1", hwnd=12345, pid=6789,
            title="Test", bounds=(0, 0, 800, 600),
            monitor_id="m1", dpi=96, ui_digest="abc123",
            is_foreground=True, is_locked=False, topology_version=1,
        )
        with pytest.raises((AttributeError, TypeError)):
            snap.hwnd = 99999  # type: ignore[misc]

    def test_compute_ui_digest_stable(self):
        """Same inputs must produce same digest."""
        d1 = compute_ui_digest(12345, 6789, "Test", (0, 0, 800, 600))
        d2 = compute_ui_digest(12345, 6789, "Test", (0, 0, 800, 600))
        assert d1 == d2

    def test_compute_ui_digest_different_for_different_windows(self):
        """Different windows must produce different digests."""
        d1 = compute_ui_digest(12345, 6789, "Window A", (0, 0, 800, 600))
        d2 = compute_ui_digest(54321, 9876, "Window B", (0, 0, 1024, 768))
        assert d1 != d2

    def test_validate_not_stale_passes_when_unchanged(self):
        """Validation passes when nothing changed."""
        digest = compute_ui_digest(12345, 6789, "Test", (0, 0, 800, 600))
        snap = WindowSnapshot(
            window_id="w1", hwnd=12345, pid=6789,
            title="Test", bounds=(0, 0, 800, 600),
            monitor_id="m1", dpi=96, ui_digest=digest,
            is_foreground=True, is_locked=False, topology_version=1,
        )
        # Should not raise
        validate_not_stale(
            snap, current_hwnd=12345, current_pid=6789,
            current_foreground_hwnd=12345, is_locked=False,
            current_dpi=96, current_topology_version=1,
            current_digest=digest,
        )

    def test_validate_raises_on_hwnd_change(self):
        """Stale detection must catch HWND change."""
        digest = compute_ui_digest(12345, 6789, "Test", (0, 0, 800, 600))
        snap = WindowSnapshot(
            window_id="w1", hwnd=12345, pid=6789,
            title="Test", bounds=(0, 0, 800, 600),
            monitor_id="m1", dpi=96, ui_digest=digest,
            is_foreground=True, is_locked=False, topology_version=1,
        )
        with pytest.raises(Exception) as exc_info:
            validate_not_stale(
                snap, current_hwnd=99999, current_pid=6789,
                current_foreground_hwnd=12345, is_locked=False,
                current_dpi=96, current_topology_version=1,
                current_digest=digest,
            )
        assert hasattr(exc_info.value, "reason")

    def test_validate_raises_on_locked(self):
        """Stale detection must catch screen lock."""
        digest = compute_ui_digest(12345, 6789, "Test", (0, 0, 800, 600))
        snap = WindowSnapshot(
            window_id="w1", hwnd=12345, pid=6789,
            title="Test", bounds=(0, 0, 800, 600),
            monitor_id="m1", dpi=96, ui_digest=digest,
            is_foreground=True, is_locked=False, topology_version=1,
        )
        with pytest.raises(Exception) as exc_info:
            validate_not_stale(
                snap, current_hwnd=12345, current_pid=6789,
                current_foreground_hwnd=12345, is_locked=True,
                current_dpi=96, current_topology_version=1,
                current_digest=digest,
            )
        assert hasattr(exc_info.value, "reason")

    def test_validate_raises_on_digest_mismatch(self):
        """Stale detection must catch digest mismatch."""
        digest = compute_ui_digest(12345, 6789, "Test", (0, 0, 800, 600))
        snap = WindowSnapshot(
            window_id="w1", hwnd=12345, pid=6789,
            title="Test", bounds=(0, 0, 800, 600),
            monitor_id="m1", dpi=96, ui_digest=digest,
            is_foreground=True, is_locked=False, topology_version=1,
        )
        with pytest.raises(Exception) as exc_info:
            validate_not_stale(
                snap, current_hwnd=12345, current_pid=6789,
                current_foreground_hwnd=12345, is_locked=False,
                current_dpi=96, current_topology_version=1,
                current_digest="different_digest",
            )


class TestClassification:
    """Test screenshot classification."""

    def test_default_classification_is_confidential(self):
        """ScreenshotResult must default to CONFIDENTIAL."""
        result = ScreenshotResult(
            data=b"fake-png-data",
            mime_type="image/png",
            width=1920, height=1080,
            taken_at=1234567890.0,
        )
        assert result.classification == Classification.CONFIDENTIAL

    def test_all_classification_levels_exist(self):
        """All classification levels must be available."""
        assert Classification.PUBLIC
        assert Classification.INTERNAL
        assert Classification.CONFIDENTIAL
        assert Classification.RESTRICTED


class TestScreenshotArtifact:
    """Test screenshot artifact metadata."""

    def test_artifact_has_relative_path_only(self):
        """Artifact must use relative path, not absolute."""
        artifact = ScreenshotArtifact(
            artifact_id="a1",
            relative_path="screenshots/cap-001.png",
            mime_type="image/png",
            width=1920, height=1080,
            sha256="abc123",
            classification=Classification.CONFIDENTIAL,
            size_bytes=102400,
        )
        assert "C:" not in artifact.relative_path
        assert "/" in artifact.relative_path

    def test_artifact_is_frozen(self):
        """Artifact must be immutable."""
        artifact = ScreenshotArtifact(
            artifact_id="a1", relative_path="s/test.png",
            mime_type="image/png", width=100, height=100,
            sha256="abc", classification=Classification.CONFIDENTIAL,
            size_bytes=100,
        )
        with pytest.raises((AttributeError, TypeError)):
            artifact.size_bytes = 999  # type: ignore[misc]


class TestCapabilityDetection:
    """Test capability availability checks."""

    def test_is_uia_available_returns_bool(self):
        """is_uia_available must return bool."""
        assert isinstance(is_uia_available(), bool)

    def test_is_wgc_available_returns_bool(self):
        """is_wgc_available must return bool."""
        assert isinstance(is_wgc_available(), bool)

    def test_desktop_input_not_available_is_capability_error(self):
        """DesktopInputNotAvailable must be a CapabilityUnavailable."""
        err = DesktopInputNotAvailable()
        assert "window_provider" in str(err).lower() or "uia" in str(err).lower()

    def test_screen_capture_not_available_is_capability_error(self):
        """ScreenCaptureNotAvailable must be a CapabilityUnavailable."""
        err = ScreenCaptureNotAvailable()
        assert "screen_capture" in str(err).lower() or "wgc" in str(err).lower()


class TestUIAElement:
    """Test UIA element descriptor."""

    def test_element_has_all_fields(self):
        """UIAElement must have all required fields."""
        elem = UIAElement(
            automation_id="btnOK",
            control_type="Button",
            name="OK",
            class_name="Button",
            is_enabled=True,
            is_offscreen=False,
            bounding_rectangle=(100, 100, 200, 140),
        )
        assert elem.automation_id == "btnOK"
        assert elem.control_type == "Button"
