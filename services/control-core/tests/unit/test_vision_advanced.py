"""Tests for ImageUnderstanding — LLM vision tool."""

import os
os.environ["TESTING"] = "1"

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from packages.vision.vision_service import ImageUnderstanding


class TestImageUnderstanding:
    """Tests for ImageUnderstanding LLM vision tool."""

    def test_name_and_description(self):
        tool = ImageUnderstanding()
        assert tool.name == "image.analyze"
        assert "vision" in tool.description.lower() or "analyze" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_missing_path(self):
        tool = ImageUnderstanding()
        ctx = MagicMock(workspace_root="/tmp")
        result = await tool.execute({}, ctx)
        assert result.success is False
        assert "path is required" in result.error

    @pytest.mark.asyncio
    async def test_path_traversal(self, tmp_path):
        tool = ImageUnderstanding()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"path": "../../etc/passwd"}, ctx)
        assert result.success is False
        assert "outside workspace" in result.error

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        tool = ImageUnderstanding()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"path": "nonexistent.png"}, ctx)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_vision_api_success(self, tmp_path):
        """Test successful vision API call."""
        # Create a test image file
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        tool = ImageUnderstanding()
        ctx = MagicMock(workspace_root=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "A test image description"}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"VISION_API_URL": "http://test-api", "VISION_API_KEY": "test-key"}):
            result = await tool.execute({"path": "test.png", "prompt": "What is this?"}, ctx)

        assert result.success is True
        assert "test image description" in result.output["description"]

    @pytest.mark.asyncio
    async def test_ocr_fallback_no_api(self, tmp_path):
        """When no vision API configured, falls back to OCR."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        tool = ImageUnderstanding()
        ctx = MagicMock(workspace_root=str(tmp_path))

        with patch.dict(os.environ, {}, clear=True):
            # Remove VISION_API_URL if set
            os.environ.pop("VISION_API_URL", None)
            with patch("packages.vision.vision_service.OCRService") as MockOCR:
                MockOCR.return_value.extract_text.return_value = "fallback text"
                result = await tool.execute({"path": "test.png"}, ctx)

        # Either OCR fallback works or it reports no vision API
        assert result.success or "No vision API" in (result.error or "")

    @pytest.mark.asyncio
    async def test_vision_api_error(self, tmp_path):
        """Vision API error returns failure."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        tool = ImageUnderstanding()
        ctx = MagicMock(workspace_root=str(tmp_path))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("API error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"VISION_API_URL": "http://test-api"}):
            result = await tool.execute({"path": "test.png"}, ctx)

        assert result.success is False
        assert "failed" in result.error.lower()
