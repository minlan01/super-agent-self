"""Tests for Voice system — STT, TTS, VoiceCommandRouter."""

import os
from unittest.mock import patch, MagicMock

from packages.voice.voice_service import SpeechToText, TextToSpeech, VoiceCommandRouter

# ── SpeechToText ──────────────────────────────────────────────────────────────


class TestSpeechToText:
    def test_no_engine_available(self):
        with patch.dict("sys.modules", {"whisper": None, "speech_recognition": None}):
            stt = SpeechToText()
            assert stt.is_available is False
            assert stt.available_engines == []

    def test_transcribe_missing_file(self):
        stt = SpeechToText()
        result = stt.transcribe("/nonexistent/audio.wav")
        assert result == ""

    @patch.object(SpeechToText, "_detect_engines", return_value=[])
    def test_transcribe_no_engine_returns_empty(self, _):
        stt = SpeechToText()
        assert stt.transcribe("/some/file.wav") == ""

    def test_cloud_stt_detected_when_env_set(self):
        with patch.dict(os.environ, {"STT_API_URL": "http://test-stt-api"}):
            stt = SpeechToText()
            assert "cloud_stt" in stt.available_engines

    def test_cloud_stt_not_detected_without_env(self):
        env = {k: v for k, v in os.environ.items() if k != "STT_API_URL"}
        with patch.dict(os.environ, env, clear=True):
            stt = SpeechToText()
            assert "cloud_stt" not in stt.available_engines

    def test_cloud_stt_transcribe_success(self, tmp_path):
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 100)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"text": "hello"}

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"STT_API_URL": "http://test-stt-api"}), \
             patch.dict("sys.modules", {"whisper": None, "speech_recognition": None}), \
             patch("httpx.Client", return_value=mock_client):
            stt = SpeechToText()
            result = stt.transcribe(str(audio))
        assert result == "hello"

    def test_cloud_stt_transcribe_failure(self, tmp_path):
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 100)

        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"STT_API_URL": "http://test-stt-api"}), \
             patch.dict("sys.modules", {"whisper": None, "speech_recognition": None}), \
             patch("httpx.Client", return_value=mock_client):
            stt = SpeechToText()
            result = stt.transcribe(str(audio))
        assert result == ""


# ── TextToSpeech ──────────────────────────────────────────────────────────────


class TestTextToSpeech:
    @patch.object(TextToSpeech, "_detect_availability", return_value=False)
    def test_not_available_when_no_engine(self, _):
        tts = TextToSpeech()
        assert tts.is_available is False

    def test_synthesize_empty_text_returns_none(self):
        tts = TextToSpeech()
        tts._available = True
        result = tts.synthesize("")
        assert result is None

    def test_synthesize_no_engine_returns_none(self):
        """Both pyttsx3 and edge_tts not importable → None."""
        with patch.dict("sys.modules", {"pyttsx3": None, "edge_tts": None}):
            tts = TextToSpeech()
            result = tts.synthesize("Hello world")
            assert result is None

    def test_chinese_voice_mapping(self):
        """Verify zh voice maps to zh-CN-XiaoxiaoNeural via edge_tts."""
        mock_communicate = MagicMock()
        mock_communicate.return_value.save = MagicMock(return_value=None)

        mock_edge_tts = MagicMock()
        mock_edge_tts.Communicate = mock_communicate

        with patch.dict("sys.modules", {"pyttsx3": None, "edge_tts": mock_edge_tts}):
            tts = TextToSpeech()
            tts._available = True
            result = tts.synthesize("你好世界", voice="zh")

        mock_communicate.assert_called_once_with("你好世界", "zh-CN-XiaoxiaoNeural")


# ── VoiceCommandRouter ────────────────────────────────────────────────────────


class TestVoiceCommandRouter:
    def setup_method(self):
        self.router = VoiceCommandRouter()

    def test_cancel_command(self):
        result = self.router.route("stop what you're doing")
        assert result["action"] == "cancel"
        assert result["transcript"] == "stop what you're doing"
        assert result["confidence"] > 0

    def test_status_command(self):
        result = self.router.route("what's the status")
        assert result["action"] == "status"

    def test_remind_command(self):
        result = self.router.route("remind me to buy groceries")
        assert result["action"] == "remind"

    def test_browse_command(self):
        result = self.router.route("open example.com")
        assert result["action"] == "browse"

    def test_read_command(self):
        result = self.router.route("read this page")
        assert result["action"] == "read"

    def test_save_command(self):
        result = self.router.route("save this document")
        assert result["action"] == "save"

    def test_search_command(self):
        result = self.router.route("search for python tutorials")
        assert result["action"] == "search"

    def test_chinese_search_command(self):
        result = self.router.route("搜索Python教程")
        assert result["action"] == "search"

    def test_unknown_command_falls_to_chat(self):
        # "hello there friend" — no keyword matches any pattern
        result = self.router.route("hello there friend")
        assert result["action"] == "chat"
        assert result["confidence"] == 0.5

    def test_result_has_all_fields(self):
        result = self.router.route("cancel the task")
        assert "action" in result
        assert "transcript" in result
        assert "confidence" in result

    def test_first_match_wins(self):
        # "open" appears before "save" in the command list
        result = self.router.route("open and save this file")
        assert result["action"] == "browse"
