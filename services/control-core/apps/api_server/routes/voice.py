"""Voice API routes — STT, TTS, and voice command routing."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from apps.api_server.dependencies import require_permission
from packages.agent_core.schemas import TaskExecutionResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB

_ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".webm", ".aac"}


def _safe_audio_suffix(filename: str | None) -> str:
    import os
    suffix = os.path.splitext(filename or "audio.wav")[1].lower()
    if suffix not in _ALLOWED_AUDIO_SUFFIXES:
        suffix = ".wav"
    return suffix


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    voice: str = Field("default", max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")


class VoiceCommandRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=2000)


class VoiceCommandResponse(BaseModel):
    action: str
    transcript: str
    confidence: float


@router.post("/stt", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("voice", "write"))])
async def speech_to_text(file: UploadFile = File(...)):
    """Upload audio file, transcribe to text."""
    import asyncio
    import os
    import tempfile

    from packages.voice.voice_service import SpeechToText

    stt = SpeechToText()
    if not stt.is_available:
        raise HTTPException(status_code=501, detail="STT engine unavailable")

    suffix = _safe_audio_suffix(file.filename)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read(_MAX_AUDIO_SIZE + 1)
        if len(content) > _MAX_AUDIO_SIZE:
            raise HTTPException(status_code=413, detail=f"Audio file too large (max {_MAX_AUDIO_SIZE // (1024*1024)}MB)")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Offload blocking Whisper/cloud STT call to a worker thread to avoid blocking the event loop.
        text = await asyncio.to_thread(stt.transcribe, tmp_path)
        return {"success": True, "data": {"transcript": text}}
    finally:
        await asyncio.to_thread(os.unlink, tmp_path)


@router.post("/tts", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("voice", "write"))])
async def text_to_speech(body: TTSRequest):
    """Convert text to speech, return audio file path."""
    import asyncio

    from packages.voice.voice_service import TextToSpeech

    tts = TextToSpeech()
    if not tts.is_available:
        raise HTTPException(status_code=501, detail="TTS engine unavailable")

    output = await asyncio.to_thread(tts.synthesize, body.text, body.voice)
    if output is None:
        raise HTTPException(status_code=500, detail="TTS synthesis failed")

    return {"success": True, "data": {"audio_path": output}}


@router.post("/command", response_model=VoiceCommandResponse, dependencies=[Depends(require_permission("voice", "write"))])
def route_voice_command(body: VoiceCommandRequest):
    """Route a voice transcript to an action."""
    from packages.voice.voice_service import VoiceCommandRouter

    router_svc = VoiceCommandRouter()
    result = router_svc.route(body.transcript)
    return VoiceCommandResponse(**result)


@router.get("/tts/audio", dependencies=[Depends(require_permission("voice", "write"))])
async def get_tts_audio(
    text: str = Query(..., min_length=1, max_length=10000),
    voice: str = Query("default"),
):
    """Stream TTS audio as a file response."""
    import asyncio

    from fastapi.responses import FileResponse

    from packages.voice.voice_service import TextToSpeech

    tts = TextToSpeech()
    if not tts.is_available:
        raise HTTPException(status_code=501, detail="TTS engine unavailable")

    output = await asyncio.to_thread(tts.synthesize, text, voice)
    if output is None:
        raise HTTPException(status_code=500, detail="TTS synthesis failed")

    return FileResponse(
        output,
        media_type="audio/wav",
        filename="tts_output.wav",
    )
