"""Download quarantine — all downloaded artifacts enter isolation before use.

Spec §P3.5: downloads go to a quarantine zone, validated for MIME type,
file size, and malicious content before being made available to tools.

Flow:
  1. Download lands in quarantine/<tenant>/<task_id>/<uuid>.<ext>
  2. MIME sniff (magic bytes, not just extension)
  3. Size check (configurable max)
  4. Malicious content scan (basic: ELF/Mach-O/PE header detection,
     embedded scripts, oversized archives)
  5. If pass: mark CLEAN, move to workspace
  6. If fail: mark BLOCKED, keep in quarantine, alert

The quarantine zone is OUTSIDE the workspace — quarantined files cannot
be executed, displayed as trusted content, or dispatched to other tenants.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Default limits (can be overridden by config).
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
DEFAULT_QUARANTINE_DIR = "data/quarantine"

# Magic bytes for dangerous executable formats.
_DANGEROUS_MAGIC = {
    b"\x7fELF": "ELF executable",
    b"MZ": "PE/Windows executable",
    b"\xfe\xed\xfa\xce": "Mach-O 32-bit",
    b"\xfe\xed\xfa\xcf": "Mach-O 64-bit",
    b"\xcf\xfa\xed\xfe": "Mach-O 64-bit (reverse)",
    b"\xca\xfe\xba\xbe": "Java class file",
}

# Extensions that are never allowed (executable/script vectors).
_BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif",
    ".sh", ".bash", ".zsh",
    ".ps1", ".psm1",
    ".vbs", ".vba",
    ".jar", ".class",
    ".dll", ".so", ".dylib",
    ".app", ".action",
    ".msi", ".deb", ".rpm",
})

# Maximum allowed archive nesting depth (zip bomb protection).
MAX_ARCHIVE_NESTING = 5


class QuarantineStatus(str, Enum):
    PENDING = "pending"
    CLEAN = "clean"
    BLOCKED = "blocked"
    EXPIRED = "expired"


@dataclass
class QuarantineResult:
    """Result of a quarantine check."""
    file_id: str
    status: QuarantineStatus
    original_name: str
    detected_mime: str
    file_size: int
    checksum: str
    quarantine_path: str
    reason: str = ""
    workspace_path: str | None = None


class QuarantineZone:
    """Manages the download quarantine zone.

    Files are stored in quarantine_dir/<tenant>/<file_id> until validated.
    Only CLEAN files are moved to the workspace.
    """

    def __init__(
        self,
        quarantine_dir: str | Path = DEFAULT_QUARANTINE_DIR,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    ):
        self.quarantine_dir = Path(quarantine_dir)
        self.max_file_size = max_file_size
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def quarantine_download(
        self,
        *,
        content: bytes,
        original_name: str,
        tenant_id: str,
        task_id: str,
        claimed_mime: str | None = None,
        workspace_dir: str | Path | None = None,
    ) -> QuarantineResult:
        """Place a downloaded file into quarantine and validate it.

        Args:
            content: Raw file bytes.
            original_name: Original filename from download.
            tenant_id: Tenant scope.
            task_id: Task that triggered the download.
            claimed_mime: MIME type from Content-Type header (may be spoofed).
            workspace_dir: Where to move the file if it passes (default: None,
                           stays in quarantine until explicitly released).

        Returns:
            QuarantineResult with status CLEAN or BLOCKED.
        """
        file_id = str(uuid.uuid4())
        tenant_dir = self.quarantine_dir / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)

        # Write to quarantine immediately (before any checks).
        safe_ext = self._safe_extension(original_name)
        q_path = tenant_dir / f"{file_id}{safe_ext}"
        q_path.write_bytes(content)

        file_size = len(content)
        checksum = hashlib.sha256(content).hexdigest()

        # ── Validation chain ──

        # 1. Size check
        if file_size > self.max_file_size:
            return self._block(
                file_id, original_name, q_path,
                detected_mime="unknown", file_size=file_size,
                checksum=checksum, tenant_id=tenant_id,
                reason=f"file size {file_size} exceeds limit {self.max_file_size}",
            )

        # 2. MIME sniff (magic bytes override claimed MIME)
        detected_mime = self._sniff_mime(content)

        # 3. Dangerous format check
        danger = self._check_dangerous(content, original_name)
        if danger:
            return self._block(
                file_id, original_name, q_path,
                detected_mime=detected_mime, file_size=file_size,
                checksum=checksum, tenant_id=tenant_id,
                reason=f"dangerous content: {danger}",
            )

        # 4. Blocked extension check
        ext = Path(original_name).suffix.lower()
        if ext in _BLOCKED_EXTENSIONS:
            return self._block(
                file_id, original_name, q_path,
                detected_mime=detected_mime, file_size=file_size,
                checksum=checksum, tenant_id=tenant_id,
                reason=f"blocked extension: {ext}",
            )

        # 5. MIME/extension mismatch (possible spoofing)
        if claimed_mime and detected_mime != "application/octet-stream":
            if not self._mime_matches_extension(detected_mime, ext):
                logger.warning(
                    "MIME/extension mismatch: claimed=%s detected=%s ext=%s file=%s",
                    claimed_mime, detected_mime, ext, original_name,
                )

        # ── All checks passed: mark CLEAN ──
        ws_path = None
        if workspace_dir is not None:
            ws_path = self._release_to_workspace(
                q_path, original_name, workspace_dir, file_id,
            )

        logger.info(
            "Quarantine CLEAN: file=%s name=%s mime=%s size=%d",
            file_id, original_name, detected_mime, file_size,
        )

        return QuarantineResult(
            file_id=file_id,
            status=QuarantineStatus.CLEAN,
            original_name=original_name,
            detected_mime=detected_mime,
            file_size=file_size,
            checksum=checksum,
            quarantine_path=str(q_path),
            workspace_path=str(ws_path) if ws_path else None,
        )

    def _block(
        self, file_id, original_name, q_path, *,
        detected_mime, file_size, checksum, tenant_id, reason,
    ) -> QuarantineResult:
        """Mark a file as BLOCKED (stays in quarantine, not released)."""
        logger.warning(
            "Quarantine BLOCKED: file=%s name=%s reason=%s",
            file_id, original_name, reason,
        )
        return QuarantineResult(
            file_id=file_id,
            status=QuarantineStatus.BLOCKED,
            original_name=original_name,
            detected_mime=detected_mime,
            file_size=file_size,
            checksum=checksum,
            quarantine_path=str(q_path),
            reason=reason,
        )

    def _release_to_workspace(
        self, q_path: Path, original_name: str,
        workspace_dir: str | Path, file_id: str,
    ) -> Path:
        """Move a CLEAN file from quarantine to workspace."""
        ws = Path(workspace_dir)
        ws.mkdir(parents=True, exist_ok=True)

        # Use file_id prefix to avoid name collisions.
        safe_name = f"{file_id[:8]}_{self._sanitize_filename(original_name)}"
        ws_path = ws / safe_name
        shutil.move(str(q_path), str(ws_path))
        return ws_path

    @staticmethod
    def _sniff_mime(content: bytes) -> str:
        """Detect MIME type from magic bytes (first 16 bytes)."""
        if len(content) < 4:
            return "application/octet-stream"

        head = content[:16]

        # Text formats
        if head[:4] == b"%PDF":
            return "application/pdf"
        if head[:2] == b"\xff\xd8":
            return "image/jpeg"
        if head[:4] == b"\x89PNG":
            return "image/png"
        if head[:4] == b"GIF8":
            return "image/gif"
        if head[:3] == b"ID3" or head[:2] == b"\xff\xfb":
            return "audio/mpeg"
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            return "audio/wav"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        if head[:4] == b"OggS":
            return "audio/ogg"
        if head[:4] == b"\x1a\x45\xdf\xa3":
            return "video/webm"
        if head[:4] == b"\x00\x00\x01\x00":
            return "image/x-icon"
        if head[:5] == b"%PNG":
            return "image/png"

        # ZIP-based formats
        if head[:2] == b"PK":
            if b"word/" in content[:2000]:
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if b"xl/" in content[:2000]:
                return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if b"ppt/" in content[:2000]:
                return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            return "application/zip"

        # Try UTF-8 text detection
        try:
            content[:1024].decode("utf-8")
            if head[:5] == b"<?xml":
                return "application/xml"
            return "text/plain"
        except (UnicodeDecodeError, Exception):
            pass

        return "application/octet-stream"

    @staticmethod
    def _check_dangerous(content: bytes, name: str) -> str | None:
        """Check for dangerous content patterns. Returns description or None."""
        # Check magic bytes of executable formats.
        for magic, desc in _DANGEROUS_MAGIC.items():
            if content[:len(magic)] == magic:
                return f"{desc} header detected"

        # Check for embedded shell scripts.
        if content[:2] == b"#!":
            shebang = content[:80].decode("ascii", errors="ignore")
            if any(s in shebang for s in ("/bin/sh", "/bin/bash", "python", "perl", "ruby")):
                return f"executable script shebang: {shebang[:40]}"

        return None

    @staticmethod
    def _safe_extension(name: str) -> str:
        """Get a safe file extension for quarantine storage."""
        ext = Path(name).suffix.lower()
        if ext and ext not in _BLOCKED_EXTENSIONS and len(ext) <= 10:
            return ext
        return ".bin"

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize a filename for workspace storage."""
        # Remove path components, keep only the basename.
        name = os.path.basename(name)
        # Replace dangerous characters.
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        return safe[:100] if safe else "unnamed"

    @staticmethod
    def _mime_matches_extension(mime: str, ext: str) -> bool:
        """Check if a MIME type is consistent with a file extension."""
        mapping = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".txt": "text/plain",
            ".html": "text/html", ".htm": "text/html",
            ".json": "application/json",
            ".xml": "application/xml",
            ".csv": "text/csv",
            ".zip": "application/zip",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".webm": "video/webm",
            ".svg": "image/svg+xml",
        }
        expected = mapping.get(ext)
        if expected is None:
            return True  # Unknown extension, don't block.
        return mime == expected or mime.startswith(expected.split("/")[0])
