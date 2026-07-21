"""Vision API routes — image analysis and OCR."""

import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from apps.api_server.dependencies import require_permission
from packages.agent_core.schemas import TaskExecutionResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

_ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


def _safe_image_suffix(filename: str | None) -> str:
    suffix = os.path.splitext(filename or "image.png")[1].lower()
    if suffix not in _ALLOWED_IMAGE_SUFFIXES:
        suffix = ".png"
    return suffix


class AnalyzeRequest(BaseModel):
    prompt: str = Field(default="Describe this image in detail.", max_length=2000)


@router.post("/analyze", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("vision", "write"))])
async def analyze_image(
    file: UploadFile = File(...),
    body: AnalyzeRequest = Depends(),
):
    """Upload an image for AI-powered analysis."""
    from pathlib import Path

    from packages.vision.vision_service import ImageUnderstanding

    suffix = _safe_image_suffix(file.filename)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read(_MAX_IMAGE_SIZE + 1)
        if len(content) > _MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail=f"Image file too large (max {_MAX_IMAGE_SIZE // (1024*1024)}MB)")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        understanding = ImageUnderstanding()

        class _Ctx:
            workspace_root = tempfile.gettempdir()

        result = await understanding.execute(
            {"path": tmp_path, "prompt": body.prompt},
            _Ctx(),
        )

        if not result.success:
            logger.warning("Image analysis failed: %s", result.error)
            raise HTTPException(status_code=500, detail="Image analysis failed")

        return {"success": True, "data": result.output}
    finally:
        import asyncio as _asyncio
        await _asyncio.to_thread(os.unlink, tmp_path)


@router.post("/ocr", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("vision", "read"))])
async def ocr_image(file: UploadFile = File(...)):
    """Upload an image for OCR text extraction."""
    import asyncio

    from packages.vision.vision_service import OCRService

    suffix = _safe_image_suffix(file.filename)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read(_MAX_IMAGE_SIZE + 1)
        if len(content) > _MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail=f"Image file too large (max {_MAX_IMAGE_SIZE // (1024*1024)}MB)")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        ocr = OCRService()
        if not ocr.is_available:
            raise HTTPException(status_code=501, detail="OCR engine unavailable")

        # Offload Tesseract (sync, CPU-bound) to worker thread.
        text = await asyncio.to_thread(ocr.extract_text, tmp_path)
        return {"success": True, "data": {"text": text, "chars": len(text)}}
    finally:
        await asyncio.to_thread(os.unlink, tmp_path)
