"""Tests for Vision system — OCR, ScreenCapture, ImageOCR."""

from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from packages.vision.vision_service import ImageOCR, OCRService, ScreenCapture


def _mock_pil_imagegrab():
    """Create a mock PIL.ImageGrab module for patching."""
    mock_grab = MagicMock()
    mock_img = MagicMock()
    mock_img.width = 1920
    mock_img.height = 1080
    mock_img.save = MagicMock()
    mock_grab.grab.return_value = mock_img
    return mock_grab, mock_img


# ── OCRService ────────────────────────────────────────────────────────────────


class TestOCRService:
    @patch.object(OCRService, "_detect", return_value=False)
    def test_not_available_when_no_tesseract(self, _):
        ocr = OCRService()
        assert ocr.is_available is False

    @patch.object(OCRService, "_detect", return_value=True)
    def test_available_when_tesseract_installed(self, _):
        ocr = OCRService()
        assert ocr.is_available is True

    @patch.object(OCRService, "_detect", return_value=False)
    def test_extract_text_unavailable_returns_empty(self, _):
        ocr = OCRService()
        text = ocr.extract_text("/some/image.png")
        assert text == ""

    @patch.object(OCRService, "_detect", return_value=True)
    def test_extract_text_missing_file_returns_empty(self, _):
        ocr = OCRService()
        text = ocr.extract_text("/nonexistent/image.png")
        assert text == ""


# ── ScreenCapture ─────────────────────────────────────────────────────────────


class TestScreenCapture:
    def test_name_and_description(self):
        tool = ScreenCapture()
        assert tool.name == "screen.capture"
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_pillow_not_installed(self):
        tool = ScreenCapture()
        # Remove PIL from importable modules
        with patch.dict("sys.modules", {"PIL": None, "PIL.ImageGrab": None}):
            result = await tool.execute({}, MagicMock(workspace_root="/tmp"))
            assert result.success is False
            assert "Pillow" in result.error

    @pytest.mark.asyncio
    async def test_capture_full_screen(self, tmp_path):
        mock_grab, mock_img = _mock_pil_imagegrab()

        # Inject mock PIL.ImageGrab into sys.modules
        mock_pil = ModuleType("PIL")
        mock_pil.ImageGrab = mock_grab
        with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.ImageGrab": mock_grab}):
            tool = ScreenCapture()
            context = MagicMock(workspace_root=str(tmp_path))
            result = await tool.execute({}, context)

        assert result.success is True
        assert result.output["size"] == "1920x1080"
        assert len(result.artifacts) == 1

    @pytest.mark.asyncio
    async def test_capture_region(self, tmp_path):
        mock_grab, mock_img = _mock_pil_imagegrab()

        mock_pil = ModuleType("PIL")
        mock_pil.ImageGrab = mock_grab
        with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.ImageGrab": mock_grab}):
            tool = ScreenCapture()
            context = MagicMock(workspace_root=str(tmp_path))
            result = await tool.execute({"region": [0, 0, 800, 600]}, context)

        assert result.success is True
        mock_grab.grab.assert_called_once_with(bbox=(0, 0, 800, 600))


# ── ImageOCR ──────────────────────────────────────────────────────────────────


class TestImageOCR:
    def test_name_and_description(self):
        tool = ImageOCR()
        assert tool.name == "image.ocr"

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self):
        tool = ImageOCR()
        context = MagicMock(workspace_root="/tmp")
        result = await tool.execute({}, context)
        assert result.success is False
        assert "path" in result.error

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path):
        tool = ImageOCR()
        context = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"path": "../../etc/passwd"}, context)
        assert result.success is False
        assert "outside workspace" in result.error.lower()

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        tool = ImageOCR()
        context = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"path": "missing.png"}, context)
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ocr_not_available(self, tmp_path):
        tool = ImageOCR()
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        with patch.object(OCRService, "_detect", return_value=False):
            context = MagicMock(workspace_root=str(tmp_path))
            result = await tool.execute({"path": "test.png"}, context)

        assert result.success is False
        assert "pytesseract" in result.error

    @pytest.mark.asyncio
    async def test_ocr_success(self, tmp_path):
        tool = ImageOCR()
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        with patch.object(OCRService, "_detect", return_value=True), \
             patch.object(OCRService, "extract_text", return_value="Hello World"):
            context = MagicMock(workspace_root=str(tmp_path))
            result = await tool.execute({"path": "test.png"}, context)

        assert result.success is True
        assert result.output["text"] == "Hello World"
        assert result.output["chars"] == 11
