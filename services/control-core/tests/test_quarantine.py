"""Tests for download quarantine (P3.4) — MIME, size, malicious content."""

import os
import tempfile

import pytest

from packages.security.quarantine import (
    QuarantineStatus,
    QuarantineZone,
)


@pytest.fixture()
def qdir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "quarantine"), os.path.join(tmpdir, "workspace")


@pytest.fixture()
def zone(qdir):
    q_path, _ = qdir
    return QuarantineZone(quarantine_dir=q_path, max_file_size=1024)  # 1KB for testing


class TestQuarantine:
    def test_clean_text_file_passes(self, zone, qdir):
        q_path, ws_path = qdir
        result = zone.quarantine_download(
            content=b"Hello, world!",
            original_name="test.txt",
            tenant_id="t1", task_id="task-1",
            claimed_mime="text/plain",
            workspace_dir=ws_path,
        )
        assert result.status == QuarantineStatus.CLEAN
        assert result.detected_mime == "text/plain"
        assert result.workspace_path is not None
        assert os.path.exists(result.workspace_path)

    def test_clean_png_image_passes(self, zone, qdir):
        _, ws_path = qdir
        # Minimal PNG header
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = zone.quarantine_download(
            content=png, original_name="image.png",
            tenant_id="t1", task_id="task-1",
            workspace_dir=ws_path,
        )
        assert result.status == QuarantineStatus.CLEAN
        assert result.detected_mime == "image/png"

    def test_oversized_file_blocked(self, zone):
        """File exceeding max_file_size is blocked."""
        result = zone.quarantine_download(
            content=b"x" * 2048,  # 2KB > 1KB limit
            original_name="big.txt",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.BLOCKED
        assert "size" in result.reason.lower()

    def test_executable_blocked(self, zone):
        """ELF binary header is blocked."""
        elf = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 100
        result = zone.quarantine_download(
            content=elf, original_name="program",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.BLOCKED
        assert "ELF" in result.reason

    def test_pe_executable_blocked(self, zone):
        mz = b"MZ\x90\x00" + b"\x00" * 100
        result = zone.quarantine_download(
            content=mz, original_name="program.exe",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.BLOCKED

    def test_shell_script_blocked(self, zone):
        script = b"#!/bin/bash\nrm -rf /\n"
        result = zone.quarantine_download(
            content=script, original_name="script.sh",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.BLOCKED
        assert "script" in result.reason.lower() or "shebang" in result.reason.lower()

    def test_blocked_extension_rejected(self, zone):
        """Files with .exe/.dll/.sh extensions are blocked even if content is text."""
        result = zone.quarantine_download(
            content=b"not actually an exe",
            original_name="malware.exe",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.BLOCKED
        assert ".exe" in result.reason

    def test_jpg_detected_correctly(self, zone):
        jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        result = zone.quarantine_download(
            content=jpg, original_name="photo.jpg",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.CLEAN
        assert result.detected_mime == "image/jpeg"

    def test_pdf_detected_correctly(self, zone):
        pdf = b"%PDF-1.4\n" + b"\x00" * 50
        result = zone.quarantine_download(
            content=pdf, original_name="doc.pdf",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.CLEAN
        assert result.detected_mime == "application/pdf"

    def test_checksum_computed(self, zone):
        import hashlib
        content = b"test content for checksum"
        result = zone.quarantine_download(
            content=content, original_name="test.txt",
            tenant_id="t1", task_id="task-1",
        )
        expected = hashlib.sha256(content).hexdigest()
        assert result.checksum == expected

    def test_blocked_file_stays_in_quarantine(self, zone, qdir):
        """Blocked files must NOT be released to workspace."""
        _, ws_path = qdir
        elf = b"\x7fELF" + b"\x00" * 50
        result = zone.quarantine_download(
            content=elf, original_name="evil",
            tenant_id="t1", task_id="task-1",
            workspace_dir=ws_path,
        )
        assert result.status == QuarantineStatus.BLOCKED
        assert result.workspace_path is None
        # File remains in quarantine
        assert os.path.exists(result.quarantine_path)

    def test_mime_extension_mismatch_warns_but_passes(self, zone, qdir):
        """MIME/extension mismatch is logged but not blocked (informational)."""
        _, ws_path = qdir
        # A PNG file named .txt — mismatch but not dangerous
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        result = zone.quarantine_download(
            content=png, original_name="actually_png.txt",
            tenant_id="t1", task_id="task-1",
            claimed_mime="text/plain",
            workspace_dir=ws_path,
        )
        # Should still be CLEAN (mismatch is a warning, not a block)
        assert result.status == QuarantineStatus.CLEAN
        assert result.detected_mime == "image/png"

    def test_empty_file_handled(self, zone):
        result = zone.quarantine_download(
            content=b"", original_name="empty.txt",
            tenant_id="t1", task_id="task-1",
        )
        assert result.status == QuarantineStatus.CLEAN
        assert result.file_size == 0

    def test_filename_sanitized_in_workspace(self, zone, qdir):
        """Filenames with path traversal chars are sanitized."""
        _, ws_path = qdir
        result = zone.quarantine_download(
            content=b"safe content",
            original_name="../../../etc/passwd.txt",
            tenant_id="t1", task_id="task-1",
            workspace_dir=ws_path,
        )
        assert result.status == QuarantineStatus.CLEAN
        # The workspace path should NOT contain ../
        assert ".." not in result.workspace_path
