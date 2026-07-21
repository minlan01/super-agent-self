"""Voice System — Speech-to-Text, Text-to-Speech, and voice command routing."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SpeechToText:
    """Convert audio to text. Supports local (whisper) and fallback modes."""

    def __init__(self, engine: str = "auto"):
        self.engine = engine
        self._available_engines = self._detect_engines()

    def _detect_engines(self) -> list[str]:
        engines = []
        try:
            import whisper  # noqa: F401
            engines.append("whisper")
        except ImportError:
            pass
        try:
            import speech_recognition  # noqa: F401
            engines.append("speech_recognition")
        except ImportError:
            pass
        if os.environ.get("STT_API_URL"):
            engines.append("cloud_stt")
        return engines

    def transcribe(self, audio_path: str, language: str = "en") -> str:
        """Transcribe audio file to text.

        Returns transcribed text, or empty string on failure.
        """
        if not Path(audio_path).exists():
            logger.error("Audio file not found: %s", audio_path)
            return ""

        if "whisper" in self._available_engines and self.engine in ("auto", "whisper"):
            return self._whisper_transcribe(audio_path, language)

        if "cloud_stt" in self._available_engines and self.engine in ("auto", "cloud_stt"):
            return self._cloud_stt_transcribe(audio_path, language)

        logger.warning("No STT engine available. Install openai-whisper or SpeechRecognition.")
        return ""

    _whisper_model = None

    def _whisper_transcribe(self, audio_path: str, language: str) -> str:
        try:
            import whisper
            if SpeechToText._whisper_model is None:
                SpeechToText._whisper_model = whisper.load_model("base")
            model = SpeechToText._whisper_model
            result = model.transcribe(audio_path, language=language)
            text = result.get("text", "").strip()
            logger.info("Whisper transcription: %d chars", len(text))
            return text
        except Exception:
            logger.exception("Whisper transcription failed")
            return ""

    def _cloud_stt_transcribe(self, audio_path: str, language: str) -> str:
        base_url = os.environ.get("STT_API_URL", "")
        if not base_url:
            logger.warning("STT_API_URL not configured, cloud STT disabled.")
            return ""
        try:
            import httpx

            with open(audio_path, "rb") as f:
                audio_bytes = f.read()

            files = {"file": (Path(audio_path).name, audio_bytes)}
            data = {"language": language}
            with httpx.Client(timeout=60) as client:
                resp = client.post(f"{base_url}/v1/audio/transcriptions", files=files, data=data)
                resp.raise_for_status()
                result = resp.json()
            text = result.get("text", "").strip()
            logger.info("Cloud STT transcription: %d chars", len(text))
            return text
        except Exception:
            logger.exception("Cloud STT transcription failed")
            return ""

    @property
    def is_available(self) -> bool:
        return len(self._available_engines) > 0

    @property
    def available_engines(self) -> list[str]:
        return list(self._available_engines)


class TextToSpeech:
    """Convert text to speech. Supports local (pyttsx3) and edge-tts."""

    def __init__(self, engine: str = "auto"):
        self.engine = engine
        self._available = self._detect_availability()

    def _detect_availability(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
            return True
        except ImportError:
            pass
        # Check edge-tts via pip
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            pass
        return False

    def synthesize(
        self,
        text: str,
        output_path: str | None = None,
        voice: str = "default",
    ) -> str | None:
        """Convert text to speech audio file.

        Returns the output file path, or None on failure.
        """
        if not text:
            return None

        if output_path is None:
            output_path = str(
                Path(tempfile.gettempdir()) / f"tts_{hash(text) % 100000}.wav"
            )

        # Try pyttsx3 first (offline)
        try:
            return self._pyttsx3_synthesize(text, output_path)
        except Exception as e:
            logger.debug("pyttsx3 failed: %s", e)

        # Try edge-tts (online, better quality)
        try:
            return self._edge_tts_synthesize(text, output_path, voice=voice)
        except Exception as e:
            logger.debug("edge-tts failed: %s", e)

        logger.warning("No TTS engine available. Install pyttsx3 or edge-tts.")
        return None

    def _pyttsx3_synthesize(self, text: str, output_path: str) -> str:
        import pyttsx3
        engine = pyttsx3.init()
        engine.save_to_file(text, output_path)
        engine.runAndWait()
        logger.info("TTS saved: %s", output_path)
        return output_path

    def _edge_tts_synthesize(self, text: str, output_path: str, voice: str = "default") -> str:
        import asyncio
        import concurrent.futures

        import edge_tts

        async def _synth():
            voice_map = {
                "default": "en-US-AriaNeural",
                "zh": "zh-CN-XiaoxiaoNeural",
                "en": "en-US-AriaNeural",
            }
            voice_name = voice_map.get(voice, voice_map["default"])
            communicate = edge_tts.Communicate(text, voice_name)
            await communicate.save(output_path)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(_synth())).result()
        else:
            asyncio.run(_synth())
        logger.info("Edge TTS saved: %s", output_path)
        return output_path

    @property
    def is_available(self) -> bool:
        return self._available


class VoiceCommandRouter:
    """Routes voice commands to appropriate actions based on intent."""

    def __init__(self):
        self._commands: list[dict[str, Any]] = [
            {"pattern": ["stop", "cancel", "abort"], "action": "cancel"},
            {"pattern": ["status", "progress", "how"], "action": "status"},
            {"pattern": ["remind", "remember", "don't forget"], "action": "remind"},
            {"pattern": ["open", "browse", "go to", "visit"], "action": "browse"},
            {"pattern": ["read", "what does", "tell me about"], "action": "read"},
            {"pattern": ["save", "write", "export", "download"], "action": "save"},
            {"pattern": ["search", "find", "look for", "查找", "搜索"], "action": "search"},
        ]

    def route(self, text: str) -> dict[str, Any]:
        """Parse voice text and return routing result."""
        text_lower = text.lower().strip()

        for cmd in self._commands:
            for pattern in cmd["pattern"]:
                if pattern in text_lower:
                    return {
                        "action": cmd["action"],
                        "transcript": text,
                        "confidence": 0.8,
                    }

        return {
            "action": "chat",
            "transcript": text,
            "confidence": 0.5,
        }
