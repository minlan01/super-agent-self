"""Vision System — OCR, screen capture, and image understanding."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from packages.executor.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)

_vision_client: Any | None = None
_vision_client_lock = threading.Lock()


async def _get_vision_client() -> Any:
    import httpx
    global _vision_client
    with _vision_client_lock:
        if _vision_client is None or _vision_client.is_closed:
            _vision_client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )
    return _vision_client


class OCRService:
    """Extract text from images using Tesseract or fallback."""

    def __init__(self):
        self._available = self._detect()

    def _detect(self) -> bool:
        try:
            import pytesseract  # noqa: F401
            return True
        except ImportError:
            return False

    def extract_text(self, image_path: str, language: str = "eng") -> str:
        """Extract text from an image file."""
        if not self._available:
            logger.warning("pytesseract not installed. OCR unavailable.")
            return ""

        if not Path(image_path).exists():
            logger.error("Image not found: %s", image_path)
            return ""

        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang=language).strip()
            logger.info("OCR extracted %d chars from %s", len(text), image_path)
            return text
        except Exception:
            logger.exception("OCR failed")
            return ""

    @property
    def is_available(self) -> bool:
        return self._available


class ScreenCapture(ToolBase):
    """Capture screenshot of the screen or a specific region."""

    name = "screen.capture"
    description = "Capture a screenshot of the desktop"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        try:
            from PIL import ImageGrab
        except ImportError:
            return ToolResult(
                success=False,
                error="Pillow not installed. Install with: pip install Pillow",
            )

        region = args.get("region")  # [x1, y1, x2, y2] or None for full screen
        workspace = Path(context.workspace_root)
        output_dir = workspace / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)

        import hashlib
        import time
        filename = f"screen_{int(time.time())}_{hashlib.sha256(str(args).encode()).hexdigest()[:8]}.png"
        output_path = output_dir / filename

        try:
            if region and len(region) == 4:
                bbox = tuple(region)
            else:
                bbox = None

            def _capture():
                from PIL import ImageGrab
                if bbox:
                    img = ImageGrab.grab(bbox=bbox)
                else:
                    img = ImageGrab.grab()
                img.save(str(output_path))
                return f"{img.width}x{img.height}"

            size_str = await asyncio.to_thread(_capture)
            logger.info("Screenshot saved: %s", output_path)
            return ToolResult(
                success=True,
                output={"path": str(output_path), "size": size_str},
                artifacts=[str(output_path)],
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Screen capture failed: {e}")


class ImageOCR(ToolBase):
    """Run OCR on an image or screenshot."""

    name = "image.ocr"
    description = "Extract text from an image using OCR"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        image_path = args.get("path", "")
        if not image_path:
            return ToolResult(success=False, error="path is required")

        workspace = Path(context.workspace_root)
        target = (workspace / image_path).resolve()

        if not target.is_relative_to(workspace.resolve()):
            return ToolResult(success=False, error="Path outside workspace")

        if not target.exists():
            return ToolResult(success=False, error="File not found")

        ocr = OCRService()
        if not ocr.is_available:
            return ToolResult(
                success=False,
                error="pytesseract not installed. Install with: pip install pytesseract",
            )

        text = await asyncio.to_thread(ocr.extract_text, str(target), language=args.get("language", "eng"))
        return ToolResult(
            success=True,
            output={"text": text, "chars": len(text), "source": image_path},
        )


class ImageUnderstanding(ToolBase):
    """Analyze images using LLM vision capabilities."""

    name = "image.analyze"
    description = "Analyze an image using AI vision and return a description"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        image_path = args.get("path", "")
        prompt = args.get("prompt", "Describe this image in detail.")

        if not image_path:
            return ToolResult(success=False, error="path is required")

        workspace = Path(context.workspace_root)
        target = (workspace / image_path).resolve()

        if not target.is_relative_to(workspace.resolve()):
            return ToolResult(success=False, error="Path outside workspace")

        if not target.exists():
            return ToolResult(success=False, error="File not found")

        try:
            import base64
            import httpx
            import json
            import os

            def _read_and_encode():
                with open(str(target), "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")

            image_data = await asyncio.to_thread(_read_and_encode)

            # Determine mime type
            suffix = target.suffix.lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
            mime_type = mime_map.get(suffix, "image/png")

            # Use OpenAI-compatible vision API
            api_url = os.environ.get("VISION_API_URL", "")
            api_key = os.environ.get("VISION_API_KEY", "")
            model = os.environ.get("VISION_MODEL", "gpt-4o-mini")

            if not api_url:
                ocr = OCRService()
                text = await asyncio.to_thread(ocr.extract_text, str(target))
                if text:
                    return ToolResult(
                        success=True,
                        output={"description": f"[OCR fallback] {text}", "source": image_path},
                    )
                return ToolResult(success=False, error="No vision API configured and OCR returned no text")

            # Call vision API
            headers = {
                "Content-Type": "application/json",
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                        ],
                    }
                ],
                "max_tokens": 1000,
            }

            client = await _get_vision_client()
            resp = await client.post(f"{api_url}/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

            description = result["choices"][0]["message"]["content"]
            logger.info("Vision analysis: %d chars for %s", len(description), image_path)
            return ToolResult(
                success=True,
                output={"description": description, "source": image_path, "model": model},
            )

        except Exception as e:
            logger.exception("Image understanding failed")
            return ToolResult(success=False, error=f"Image analysis failed: {e}")
