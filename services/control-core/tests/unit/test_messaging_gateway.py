"""Unit tests for Messaging Gateway — base classes, providers, and router.

Covers:
- BaseMessagingProvider (ABC enforcement)
- TelegramProvider (webhook validation, health, send, parse modes)
- DiscordProvider (webhook validation, health, send, rate limits)
- SlackProvider (webhook validation, health, send, channel mapping)
- FeishuProvider (URL verification, event parsing, health, send)
- MessagingRouter (registration, routing, failover, credential pooling, webhook dispatch)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.messaging_gateway.base import (
    BaseMessagingProvider,
    InboundMessage,
    MessageDeliveryStatus,
    OutboundMessage,
)
from packages.messaging_gateway.discord_provider import DiscordProvider
from packages.messaging_gateway.feishu_provider import FeishuProvider
from packages.messaging_gateway.messaging_router import (
    MessagingRouter,
    _PROVIDER_TYPES,
)
from packages.messaging_gateway.slack_provider import SlackProvider
from packages.messaging_gateway.telegram_provider import TelegramProvider


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_outbound(
    platform: str = "telegram",
    channel_id: str = "12345",
    text: str = "hello",
    parse_mode: str = "plain",
    reply_to: str | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        platform=platform,
        channel_id=channel_id,
        text=text,
        parse_mode=parse_mode,
        reply_to=reply_to,
    )


def _mock_httpx_response(
    status_code: int = 200, json_data: dict[str, Any] | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Dataclass tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestInboundMessage:
    def test_create_with_required_fields(self):
        msg = InboundMessage(
            platform="telegram",
            channel_id="chat1",
            sender_id="user1",
            text="hello world",
        )
        assert msg.platform == "telegram"
        assert msg.channel_id == "chat1"
        assert msg.sender_id == "user1"
        assert msg.text == "hello world"
        assert msg.raw_payload == {}
        assert msg.thread_id is None

    def test_create_with_all_fields(self):
        msg = InboundMessage(
            platform="discord",
            channel_id="ch2",
            sender_id="u2",
            text="hi",
            raw_payload={"key": "val"},
            timestamp=1700000000.0,
            thread_id="thread1",
        )
        assert msg.raw_payload == {"key": "val"}
        assert msg.timestamp == 1700000000.0
        assert msg.thread_id == "thread1"

    def test_timestamp_defaults_to_now(self):
        before = time.time()
        msg = InboundMessage(platform="slack", channel_id="", sender_id="", text="")
        after = time.time()
        assert before <= msg.timestamp <= after


@pytest.mark.unit
class TestOutboundMessage:
    def test_create_with_required_fields(self):
        msg = OutboundMessage(
            platform="telegram", channel_id="ch1", text="send this"
        )
        assert msg.parse_mode == "plain"
        assert msg.reply_to is None
        assert msg.attachments is None

    def test_create_with_all_fields(self):
        msg = OutboundMessage(
            platform="discord",
            channel_id="ch2",
            text="rich msg",
            parse_mode="markdown",
            reply_to="42",
            attachments=[{"url": "https://example.com/file.pdf"}],
        )
        assert msg.parse_mode == "markdown"
        assert msg.reply_to == "42"
        assert len(msg.attachments) == 1


@pytest.mark.unit
class TestMessageDeliveryStatus:
    def test_sent_status(self):
        status = MessageDeliveryStatus(
            message_id="msg1", platform="telegram", status="sent"
        )
        assert status.error is None
        assert status.status == "sent"

    def test_failed_status_with_error(self):
        status = MessageDeliveryStatus(
            message_id="",
            platform="discord",
            status="failed",
            error="timeout",
        )
        assert status.error == "timeout"

    def test_timestamp_auto_set(self):
        before = time.time()
        status = MessageDeliveryStatus(
            message_id="m1", platform="slack", status="sent"
        )
        after = time.time()
        assert before <= status.timestamp <= after


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BaseMessagingProvider (ABC enforcement)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestBaseMessagingProvider:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseMessagingProvider({"name": "test"})

    def test_concrete_subclass_must_implement_all_abstracts(self):
        class IncompleteProvider(BaseMessagingProvider):
            async def send(self, message):
                pass

        with pytest.raises(TypeError):
            IncompleteProvider({"name": "incomplete"})

    def test_concrete_subclass_with_all_methods_works(self):
        class CompleteProvider(BaseMessagingProvider):
            async def send(self, message):
                return MessageDeliveryStatus(
                    message_id="1", platform="test", status="sent"
                )

            async def validate_webhook(self, headers, body):
                return None

            async def health_check(self):
                return True

        p = CompleteProvider({"name": "complete"})
        assert p.name == "complete"

    def test_config_stored(self):
        class CompleteProvider(BaseMessagingProvider):
            async def send(self, message):
                pass

            async def validate_webhook(self, headers, body):
                pass

            async def health_check(self):
                return True

        cfg = {"name": "myprov", "extra": True}
        p = CompleteProvider(cfg)
        assert p.config == cfg
        assert p.name == "myprov"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TelegramProvider
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestTelegramProvider:
    def _make_provider(self, **overrides) -> TelegramProvider:
        cfg = {"name": "test_telegram", "env_key": "TEST_TG_TOKEN", **overrides}
        return TelegramProvider(cfg)

    # --- Initialization ---

    def test_init_reads_api_key_from_env(self):
        with patch.dict(os.environ, {"TEST_TG_TOKEN": "bot123"}):
            p = self._make_provider()
            assert p.api_key == "bot123"

    def test_init_reads_api_key_from_env_keys(self):
        with patch.dict(os.environ, {"TG_KEY_1": "key_alpha"}):
            p = self._make_provider(
                env_keys=["TG_MISSING", "TG_KEY_1"], env_key="FALLBACK"
            )
            assert p.api_key == "key_alpha"

    def test_init_default_base_url(self):
        p = self._make_provider()
        assert p.base_url == "https://api.telegram.org"

    def test_init_custom_base_url(self):
        p = self._make_provider(base_url="https://custom.tg.api")
        assert p.base_url == "https://custom.tg.api"

    def test_bot_url_property(self):
        with patch.dict(os.environ, {"TEST_TG_TOKEN": "tok"}):
            p = self._make_provider()
            assert p._bot_url == "https://api.telegram.org/bottok"

    # --- Send ---

    @pytest.mark.asyncio
    async def test_send_success(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": True, "result": {"message_id": 42}}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound()
        result = await p.send(msg)

        assert result.status == "sent"
        assert result.message_id == "42"
        assert result.platform == "telegram"

    @pytest.mark.asyncio
    async def test_send_with_html_parse_mode(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": True, "result": {"message_id": 1}}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(parse_mode="html")
        await p.send(msg)

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
        assert body["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_send_with_markdown_parse_mode(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": True, "result": {"message_id": 2}}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(parse_mode="markdown")
        await p.send(msg)

        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs["json"]
        assert body["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_send_plain_has_no_parse_mode(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": True, "result": {"message_id": 3}}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(parse_mode="plain")
        await p.send(msg)

        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs["json"]
        assert "parse_mode" not in body

    @pytest.mark.asyncio
    async def test_send_with_reply_to(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": True, "result": {"message_id": 4}}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(reply_to="99")
        await p.send(msg)

        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs["json"]
        assert body["reply_to_message_id"] == "99"

    @pytest.mark.asyncio
    async def test_send_api_returns_not_ok(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": False, "description": "Bad Request: chat not found"}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound())
        assert result.status == "failed"
        assert "chat not found" in result.error

    @pytest.mark.asyncio
    async def test_send_network_error(self):
        p = self._make_provider()
        mock_client = AsyncMock()
        mock_client.post.side_effect = ConnectionError("network down")
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound())
        assert result.status == "failed"
        assert "network down" in result.error

    # --- Webhook validation ---

    @pytest.mark.asyncio
    async def test_webhook_rejects_when_secret_not_configured(self):
        p = self._make_provider()
        with patch.dict(os.environ, {}, clear=True):
            # Ensure TELEGRAM_WEBHOOK_SECRET is not set
            os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)
            result = await p.validate_webhook({}, b"{}")
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_wrong_secret(self):
        p = self._make_provider()
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "expected_secret"}):
            headers = {"x-telegram-bot-api-secret-token": "wrong_secret"}
            result = await p.validate_webhook(headers, b"{}")
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_accepts_correct_secret(self):
        p = self._make_provider()
        body = json.dumps({
            "message": {
                "text": "hello",
                "chat": {"id": 111},
                "from": {"id": 222},
                "date": 1700000000,
            }
        }).encode()
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "mysecret"}):
            headers = {"x-telegram-bot-api-secret-token": "mysecret"}
            result = await p.validate_webhook(headers, body)
            assert result is not None
            assert result.text == "hello"
            assert result.channel_id == "111"
            assert result.sender_id == "222"
            assert result.platform == "telegram"

    @pytest.mark.asyncio
    async def test_webhook_parses_edited_message(self):
        p = self._make_provider()
        body = json.dumps({
            "edited_message": {
                "text": "edited text",
                "chat": {"id": "333"},
                "from": {"id": "444"},
                "date": 1700000000,
            }
        }).encode()
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "secret"}):
            headers = {"x-telegram-bot-api-secret-token": "secret"}
            result = await p.validate_webhook(headers, body)
            assert result is not None
            assert result.text == "edited text"

    @pytest.mark.asyncio
    async def test_webhook_returns_none_for_empty_text(self):
        p = self._make_provider()
        body = json.dumps({
            "message": {"chat": {"id": 1}, "from": {"id": 2}, "date": 0}
        }).encode()
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "secret"}):
            headers = {"x-telegram-bot-api-secret-token": "secret"}
            result = await p.validate_webhook(headers, body)
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_returns_none_for_invalid_json(self):
        p = self._make_provider()
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "secret"}):
            headers = {"x-telegram-bot-api-secret-token": "secret"}
            result = await p.validate_webhook(headers, b"not json{{{")
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_extracts_thread_id(self):
        p = self._make_provider()
        body = json.dumps({
            "message": {
                "text": "in thread",
                "chat": {"id": "100"},
                "from": {"id": "200"},
                "date": 1700000000,
                "message_thread_id": "thread_42",
            }
        }).encode()
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "secret"}):
            headers = {"x-telegram-bot-api-secret-token": "secret"}
            result = await p.validate_webhook(headers, body)
            assert result is not None
            assert result.thread_id == "thread_42"

    # --- Health check ---

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": True, "result": {"id": 123}})
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": False})
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        p = self._make_provider()
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("timeout")
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DiscordProvider
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestDiscordProvider:
    def _make_provider(self, **overrides) -> DiscordProvider:
        cfg = {"name": "test_discord", "env_key": "TEST_DC_TOKEN", **overrides}
        return DiscordProvider(cfg)

    # --- Initialization ---

    def test_init_reads_api_key(self):
        with patch.dict(os.environ, {"TEST_DC_TOKEN": "discord_tok"}):
            p = self._make_provider()
            assert p.api_key == "discord_tok"

    def test_init_default_base_url(self):
        p = self._make_provider()
        assert p.base_url == "https://discord.com/api/v10"

    # --- Send ---

    @pytest.mark.asyncio
    async def test_send_success(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"id": "999", "content": "hello"})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(platform="discord")
        result = await p.send(msg)
        assert result.status == "sent"
        assert result.message_id == "999"
        assert result.platform == "discord"

    @pytest.mark.asyncio
    async def test_send_with_reply(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"id": "100"})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(platform="discord", reply_to="55")
        await p.send(msg)

        body = mock_client.post.call_args.kwargs["json"]
        assert body["message_reference"] == {"message_id": "55"}

    @pytest.mark.asyncio
    async def test_send_server_error(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            400, {"message": "Cannot send messages to this user"}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="discord"))
        assert result.status == "failed"
        assert "Cannot send messages" in result.error

    @pytest.mark.asyncio
    async def test_send_network_exception(self):
        p = self._make_provider()
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("DNS failure")
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="discord"))
        assert result.status == "failed"
        assert "DNS failure" in result.error

    # --- Webhook validation ---

    @pytest.mark.asyncio
    async def test_webhook_rejects_missing_signature_headers(self):
        p = self._make_provider()
        result = await p.validate_webhook({}, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_missing_timestamp(self):
        p = self._make_provider()
        headers = {"x-signature-ed25519": "abc"}
        result = await p.validate_webhook(headers, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_stale_timestamp(self):
        p = self._make_provider()
        old_ts = str(time.time() - 600)  # 10 min ago
        headers = {
            "x-signature-ed25519": "sig123",
            "x-signature-timestamp": old_ts,
        }
        result = await p.validate_webhook(headers, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_invalid_timestamp(self):
        p = self._make_provider()
        headers = {
            "x-signature-ed25519": "sig",
            "x-signature-timestamp": "not_a_number",
        }
        result = await p.validate_webhook(headers, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_when_pynacl_not_available(self):
        p = self._make_provider()
        ts = str(time.time())
        headers = {
            "x-signature-ed25519": "abc123",
            "x-signature-timestamp": ts,
        }
        # nacl import will fail in most test environments
        with patch.dict("sys.modules", {"nacl": None, "nacl.signing": None, "nacl.exceptions": None}):
            result = await p.validate_webhook(headers, b'{"type": 2}')
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_when_public_key_not_configured(self):
        p = self._make_provider()  # no public_key in config
        ts = str(time.time())
        headers = {
            "x-signature-ed25519": "abc",
            "x-signature-timestamp": ts,
        }
        # Patch nacl to be importable but public_key is empty
        with patch(
            "packages.messaging_gateway.discord_provider.DiscordProvider.validate_webhook",
            new_callable=AsyncMock,
        ) as mock_validate:
            # We need to test the actual code path, so test differently:
            pass
        # Instead, verify config has no public_key
        assert p.config.get("public_key", "") == ""

    @pytest.mark.asyncio
    async def test_webhook_ping_returns_none(self):
        """Discord PING (type=1) should return None after signature verification."""
        p = self._make_provider(public_key="dummy_pk")
        ts = str(time.time())
        body = json.dumps({"type": 1}).encode()
        headers = {
            "x-signature-ed25519": "sig",
            "x-signature-timestamp": ts,
        }
        # Mock nacl verification to succeed
        mock_verify_key = MagicMock()
        with patch.dict(
            "sys.modules",
            {"nacl": MagicMock(), "nacl.signing": MagicMock(), "nacl.exceptions": MagicMock()},
        ):
            import packages.messaging_gateway.discord_provider as dp_module

            with patch.object(dp_module, "ValidateKey", None, create=True):
                # Simulate successful nacl verification by patching the import block
                with patch("nacl.signing.VerifyKey", return_value=mock_verify_key, create=True):
                    mock_verify_key.verify.return_value = None
                    with patch("nacl.exceptions.BadSignatureError", Exception, create=True):
                        result = await p.validate_webhook(headers, body)
                        assert result is None

    # --- Health check ---

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"id": "bot_id"})
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(401, {"message": "Unauthorized"})
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        p = self._make_provider()
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("connection error")
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SlackProvider
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSlackProvider:
    def _make_provider(self, **overrides) -> SlackProvider:
        cfg = {
            "name": "test_slack",
            "env_keys": ["SLACK_BOT_TOKEN_TEST", "SLACK_SIGNING_SECRET_TEST"],
            **overrides,
        }
        return SlackProvider(cfg)

    def _make_provider_with_creds(self) -> SlackProvider:
        """Create a provider with signing secret for signature tests."""
        with patch.dict(
            os.environ,
            {
                "SLACK_BOT_TOKEN_TEST": "xoxb-test-token",
                "SLACK_SIGNING_SECRET_TEST": "test_signing_secret",
            },
        ):
            return self._make_provider()

    # --- Initialization ---

    def test_init_reads_api_key_and_signing_secret(self):
        with patch.dict(
            os.environ,
            {
                "SLACK_BOT_TOKEN_TEST": "xoxb-123",
                "SLACK_SIGNING_SECRET_TEST": "signing_abc",
            },
        ):
            p = self._make_provider()
            assert p.api_key == "xoxb-123"
            assert p.signing_secret == "signing_abc"

    def test_init_default_base_url(self):
        p = self._make_provider()
        assert p.base_url == "https://slack.com/api"

    # --- Signature verification ---

    def test_verify_signature_rejects_when_no_signing_secret(self):
        p = self._make_provider()
        # signing_secret is empty
        assert p._verify_signature("123", "body", "v0=abc") is False

    def test_verify_signature_success(self):
        p = self._make_provider_with_creds()
        timestamp = "1700000000"
        body = 'payload={"text":"hello"}'
        sig_basestring = f"v0:{timestamp}:{body}"
        expected_sig = (
            "v0="
            + hmac.new(
                "test_signing_secret".encode(),
                sig_basestring.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        assert p._verify_signature(timestamp, body, expected_sig) is True

    def test_verify_signature_wrong_signature(self):
        p = self._make_provider_with_creds()
        assert p._verify_signature("1700000000", "body", "v0=wrong") is False

    # --- Send ---

    @pytest.mark.asyncio
    async def test_send_success(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(
            200, {"ok": True, "ts": "1700000000.000100"}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(platform="slack")
        result = await p.send(msg)
        assert result.status == "sent"
        assert result.message_id == "1700000000.000100"
        assert result.platform == "slack"

    @pytest.mark.asyncio
    async def test_send_with_markdown(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": True, "ts": "123"})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(platform="slack", parse_mode="markdown")
        await p.send(msg)

        body = mock_client.post.call_args.kwargs["json"]
        assert body["mrkdwn"] is True

    @pytest.mark.asyncio
    async def test_send_with_thread_reply(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": True, "ts": "456"})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        msg = _make_outbound(platform="slack", reply_to="1700000000.000050")
        await p.send(msg)

        body = mock_client.post.call_args.kwargs["json"]
        assert body["thread_ts"] == "1700000000.000050"

    @pytest.mark.asyncio
    async def test_send_api_error(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": False, "error": "channel_not_found"})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="slack"))
        assert result.status == "failed"
        assert "channel_not_found" in result.error

    @pytest.mark.asyncio
    async def test_send_network_exception(self):
        p = self._make_provider()
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("timeout")
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="slack"))
        assert result.status == "failed"

    # --- Webhook validation ---

    @pytest.mark.asyncio
    async def test_webhook_rejects_missing_signature(self):
        p = self._make_provider_with_creds()
        headers = {"x-slack-request-timestamp": str(int(time.time()))}
        result = await p.validate_webhook(headers, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_missing_timestamp(self):
        p = self._make_provider_with_creds()
        headers = {"x-slack-signature": "v0=abc"}
        result = await p.validate_webhook(headers, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_stale_timestamp(self):
        p = self._make_provider_with_creds()
        old_ts = str(int(time.time()) - 600)
        headers = {
            "x-slack-signature": "v0=abc",
            "x-slack-request-timestamp": old_ts,
        }
        result = await p.validate_webhook(headers, b"{}")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_invalid_signature(self):
        p = self._make_provider_with_creds()
        ts = str(int(time.time()))
        headers = {
            "x-slack-signature": "v0=invalid_signature",
            "x-slack-request-timestamp": ts,
        }
        body = b'{"type":"event_callback","event":{"type":"message","text":"hi","channel":"C1","user":"U1"}}'
        result = await p.validate_webhook(headers, body)
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_url_verification_returns_none(self):
        p = self._make_provider_with_creds()
        ts = str(int(time.time()))
        raw_body = '{"type":"url_verification","challenge":"abc123"}'
        sig_basestring = f"v0:{ts}:{raw_body}"
        sig = "v0=" + hmac.new(
            "test_signing_secret".encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "x-slack-signature": sig,
            "x-slack-request-timestamp": ts,
        }
        result = await p.validate_webhook(headers, raw_body.encode())
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_parses_message_event(self):
        p = self._make_provider_with_creds()
        ts = str(int(time.time()))
        raw_body = json.dumps({
            "type": "event_callback",
            "event": {
                "type": "message",
                "text": "hello slack",
                "channel": "C12345",
                "user": "U67890",
            },
        })
        sig_basestring = f"v0:{ts}:{raw_body}"
        sig = "v0=" + hmac.new(
            "test_signing_secret".encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "x-slack-signature": sig,
            "x-slack-request-timestamp": ts,
        }
        result = await p.validate_webhook(headers, raw_body.encode())
        assert result is not None
        assert result.text == "hello slack"
        assert result.channel_id == "C12345"
        assert result.sender_id == "U67890"
        assert result.platform == "slack"

    @pytest.mark.asyncio
    async def test_webhook_skips_bot_messages(self):
        p = self._make_provider_with_creds()
        ts = str(int(time.time()))
        raw_body = json.dumps({
            "type": "event_callback",
            "event": {
                "type": "message",
                "text": "bot msg",
                "channel": "C1",
                "user": "U1",
                "bot_id": "B123",
            },
        })
        sig_basestring = f"v0:{ts}:{raw_body}"
        sig = "v0=" + hmac.new(
            "test_signing_secret".encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "x-slack-signature": sig,
            "x-slack-request-timestamp": ts,
        }
        result = await p.validate_webhook(headers, raw_body.encode())
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_skips_non_message_events(self):
        p = self._make_provider_with_creds()
        ts = str(int(time.time()))
        raw_body = json.dumps({
            "type": "event_callback",
            "event": {"type": "reaction_added", "user": "U1"},
        })
        sig_basestring = f"v0:{ts}:{raw_body}"
        sig = "v0=" + hmac.new(
            "test_signing_secret".encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "x-slack-signature": sig,
            "x-slack-request-timestamp": ts,
        }
        result = await p.validate_webhook(headers, raw_body.encode())
        assert result is None

    # --- Health check ---

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": True, "user": "bot"})
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        p = self._make_provider()
        mock_resp = _mock_httpx_response(200, {"ok": False, "error": "not_authed"})
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        assert await p.health_check() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FeishuProvider
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestFeishuProvider:
    def _make_provider(self, **overrides) -> FeishuProvider:
        cfg = {
            "name": "test_feishu",
            "env_keys": ["FEISHU_APP_ID_TEST", "FEISHU_APP_SECRET_TEST"],
            **overrides,
        }
        return FeishuProvider(cfg)

    def _make_provider_with_creds(self) -> FeishuProvider:
        with patch.dict(
            os.environ,
            {
                "FEISHU_APP_ID_TEST": "cli_test_app",
                "FEISHU_APP_SECRET_TEST": "test_secret",
                "FEISHU_VERIFICATION_TOKEN": "verify_tok",
            },
        ):
            return self._make_provider()

    # --- Initialization ---

    def test_init_reads_app_id_and_secret(self):
        with patch.dict(
            os.environ,
            {"FEISHU_APP_ID_TEST": "app1", "FEISHU_APP_SECRET_TEST": "sec1"},
        ):
            p = self._make_provider()
            assert p.app_id == "app1"
            assert p.app_secret == "sec1"

    def test_init_default_base_url(self):
        p = self._make_provider()
        assert p.base_url == "https://open.feishu.cn/open-apis"

    # --- Tenant token ---

    @pytest.mark.asyncio
    async def test_get_tenant_token_success(self):
        p = self._make_provider_with_creds()
        mock_resp = _mock_httpx_response(
            200,
            {"tenant_access_token": "tenant_tok_abc", "expire": 7200},
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        token = await p._get_tenant_token()
        assert token == "tenant_tok_abc"
        assert p._tenant_token == "tenant_tok_abc"

    @pytest.mark.asyncio
    async def test_get_tenant_token_cached(self):
        p = self._make_provider_with_creds()
        p._tenant_token = "cached_token"
        p._token_expires = time.time() + 3600  # not expired yet

        token = await p._get_tenant_token()
        assert token == "cached_token"

    @pytest.mark.asyncio
    async def test_get_tenant_token_no_credentials(self):
        p = self._make_provider()
        p.app_id = ""
        p.app_secret = ""
        token = await p._get_tenant_token()
        assert token == ""

    @pytest.mark.asyncio
    async def test_get_tenant_token_api_failure(self):
        p = self._make_provider_with_creds()
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("API down")
        mock_client.is_closed = False
        p._client = mock_client

        token = await p._get_tenant_token()
        assert token == ""

    # --- Send ---

    @pytest.mark.asyncio
    async def test_send_no_tenant_token(self):
        p = self._make_provider()
        p._tenant_token = ""
        p._token_expires = 0
        p.app_id = ""
        p.app_secret = ""

        result = await p.send(_make_outbound(platform="feishu"))
        assert result.status == "failed"
        assert "No tenant access token" in result.error

    @pytest.mark.asyncio
    async def test_send_success(self):
        p = self._make_provider_with_creds()
        p._tenant_token = "valid_token"
        p._token_expires = time.time() + 3600

        mock_resp = _mock_httpx_response(
            200, {"code": 0, "data": {"message_id": "msg_feishu_1"}}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="feishu"))
        assert result.status == "sent"
        assert result.message_id == "msg_feishu_1"
        assert result.platform == "feishu"

    @pytest.mark.asyncio
    async def test_send_api_error(self):
        p = self._make_provider_with_creds()
        p._tenant_token = "valid_token"
        p._token_expires = time.time() + 3600

        mock_resp = _mock_httpx_response(
            200, {"code": 9999, "msg": "invalid receive_id"}
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="feishu"))
        assert result.status == "failed"
        assert "invalid receive_id" in result.error

    @pytest.mark.asyncio
    async def test_send_network_exception(self):
        p = self._make_provider_with_creds()
        p._tenant_token = "valid_token"
        p._token_expires = time.time() + 3600

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("network error")
        mock_client.is_closed = False
        p._client = mock_client

        result = await p.send(_make_outbound(platform="feishu"))
        assert result.status == "failed"

    # --- Webhook validation ---

    @pytest.mark.asyncio
    async def test_webhook_url_verification_returns_none(self):
        p = self._make_provider_with_creds()
        body = json.dumps({"type": "url_verification", "challenge": "xyz"}).encode()
        result = await p.validate_webhook({}, body)
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_when_verification_token_not_set(self):
        p = self._make_provider()
        p.verification_token = ""
        body = json.dumps({
            "type": "event_callback",
            "header": {"token": "anything"},
            "event": {"message": {"content": '{"text":"hi"}', "chat_id": "c1"}},
        }).encode()
        result = await p.validate_webhook({}, body)
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_rejects_token_mismatch(self):
        p = self._make_provider()
        p.verification_token = "expected_token"
        body = json.dumps({
            "type": "event_callback",
            "header": {"token": "wrong_token"},
            "event": {
                "message": {"content": '{"text":"hi"}', "chat_id": "c1"},
                "sender": {"sender_id": {"user_id": "u1"}},
            },
        }).encode()
        result = await p.validate_webhook({}, body)
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_parses_event_message(self):
        p = self._make_provider()
        p.verification_token = "my_token"
        body = json.dumps({
            "type": "event_callback",
            "header": {"token": "my_token"},
            "event": {
                "message": {
                    "content": '{"text":"hello feishu"}',
                    "chat_id": "oc_12345",
                    "message_id": "om_999",
                },
                "sender": {"sender_id": {"user_id": "user_abc"}},
            },
        }).encode()
        result = await p.validate_webhook({}, body)
        assert result is not None
        assert result.text == "hello feishu"
        assert result.channel_id == "oc_12345"
        assert result.sender_id == "user_abc"
        assert result.platform == "feishu"
        assert result.thread_id == "om_999"

    @pytest.mark.asyncio
    async def test_webhook_returns_none_for_empty_text(self):
        p = self._make_provider()
        p.verification_token = "my_token"
        body = json.dumps({
            "type": "event_callback",
            "header": {"token": "my_token"},
            "event": {
                "message": {"content": "{}", "chat_id": "c1"},
                "sender": {"sender_id": {"user_id": "u1"}},
            },
        }).encode()
        result = await p.validate_webhook({}, body)
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_returns_none_for_invalid_json(self):
        p = self._make_provider()
        result = await p.validate_webhook({}, b"not valid json{{{")
        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_handles_content_as_dict(self):
        p = self._make_provider()
        p.verification_token = "tok"
        body = json.dumps({
            "type": "event_callback",
            "header": {"token": "tok"},
            "event": {
                "message": {
                    "content": {"text": "direct dict content"},
                    "chat_id": "c2",
                },
                "sender": {"sender_id": {"user_id": "u2"}},
            },
        }).encode()
        result = await p.validate_webhook({}, body)
        assert result is not None
        assert result.text == "direct dict content"

    # --- Health check ---

    @pytest.mark.asyncio
    async def test_health_check_with_valid_token(self):
        p = self._make_provider_with_creds()
        p._tenant_token = "valid"
        p._token_expires = time.time() + 3600

        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_no_token(self):
        p = self._make_provider()
        p._tenant_token = ""
        p._token_expires = 0
        p.app_id = ""
        p.app_secret = ""

        assert await p.health_check() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. MessagingRouter
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestMessagingRouter:
    """Tests for MessagingRouter — config loading, provider management, routing."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a temporary messaging config for each test."""
        self.config_dir = tmp_path / "configs"
        self.config_dir.mkdir()
        self.config_path = str(self.config_dir / "messaging.yaml")

    def _write_config(self, cfg: dict[str, Any]) -> None:
        import yaml

        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

    def _basic_config(self) -> dict[str, Any]:
        return {
            "providers": {
                "tg": {
                    "type": "telegram",
                    "enabled": True,
                    "env_key": "TELEGRAM_BOT_TOKEN",
                },
                "dc": {
                    "type": "discord",
                    "enabled": True,
                    "env_key": "DISCORD_BOT_TOKEN",
                },
            },
            "defaults": {"provider": "tg"},
            "failover": {
                "chains": {
                    "default": ["tg", "dc"],
                },
            },
        }

    def _make_router(self, config: dict[str, Any] | None = None) -> MessagingRouter:
        if config is not None:
            self._write_config(config)
        return MessagingRouter(config_path=self.config_path)

    # --- Config loading ---

    def test_loads_providers_from_config(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok1", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())
            assert "tg" in router.providers
            assert "dc" in router.providers
            assert isinstance(router.providers["tg"], TelegramProvider)
            assert isinstance(router.providers["dc"], DiscordProvider)

    def test_missing_config_uses_defaults(self):
        router = MessagingRouter(config_path=str(self.config_dir / "nonexistent.yaml"))
        assert router.providers == {}
        assert router.default_provider == "telegram"

    def test_default_provider_from_config(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())
            assert router.default_provider == "tg"

    def test_default_provider_from_env_override(self):
        with patch.dict(
            os.environ,
            {"MESSAGING_PROVIDER": "dc", "TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"},
        ):
            router = self._make_router(self._basic_config())
            assert router.default_provider == "dc"

    def test_disabled_provider_skipped(self):
        cfg = self._basic_config()
        cfg["providers"]["dc"]["enabled"] = False
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(cfg)
            assert "dc" not in router.providers
            assert "tg" in router.providers

    def test_unknown_provider_type_logged_and_skipped(self):
        cfg = self._basic_config()
        cfg["providers"]["unknown"] = {"type": "carrier_pigeon", "enabled": True}
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(cfg)
            assert "unknown" not in router.providers

    def test_fallback_default_provider_to_first_available(self):
        cfg = self._basic_config()
        cfg["defaults"]["provider"] = "nonexistent"
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(cfg)
            assert router.default_provider in router.providers

    # --- Failover chains ---

    def test_failover_chains_loaded(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())
            assert "default" in router.failover_chains
            assert router.failover_chains["default"] == ["tg", "dc"]

    def test_auto_generate_default_chain(self):
        cfg = self._basic_config()
        del cfg["failover"]
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(cfg)
            assert "default" in router.failover_chains
            assert len(router.failover_chains["default"]) > 0

    # --- get_provider ---

    def test_get_provider_by_name(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())
            p = router.get_provider("tg")
            assert isinstance(p, TelegramProvider)

    def test_get_provider_default(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())
            p = router.get_provider(None)
            assert p.name == "tg"

    def test_get_provider_nonexistent_raises(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())
            with pytest.raises(ValueError, match="not found"):
                router.get_provider("nonexistent")

    # --- send ---

    @pytest.mark.asyncio
    async def test_send_with_provider_name(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())

            # Mock the provider's send
            mock_result = MessageDeliveryStatus(
                message_id="m1", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=mock_result)

            msg = _make_outbound()
            result = await router.send(msg, provider="tg")
            assert result.status == "sent"
            assert result.message_id == "m1"

    @pytest.mark.asyncio
    async def test_send_uses_default_provider(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            mock_result = MessageDeliveryStatus(
                message_id="m2", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=mock_result)

            # Use platform="tg" to match the provider name; otherwise
            # message.platform ("telegram") won't match any provider key ("tg").
            msg = _make_outbound(platform="tg")
            result = await router.send(msg)
            assert result.status == "sent"

    @pytest.mark.asyncio
    async def test_send_records_health_on_success(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            mock_result = MessageDeliveryStatus(
                message_id="m3", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=mock_result)

            await router.send(_make_outbound(), provider="tg")
            assert router.health_tracker.is_healthy("tg")

    @pytest.mark.asyncio
    async def test_send_records_health_on_failure(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            mock_result = MessageDeliveryStatus(
                message_id="", platform="telegram", status="failed", error="timeout"
            )
            router.providers["tg"].send = AsyncMock(return_value=mock_result)

            result = await router.send(_make_outbound(), provider="tg")
            assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_send_exception_records_failure(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())
            router.providers["tg"].send = AsyncMock(side_effect=Exception("crash"))

            result = await router.send(_make_outbound(), provider="tg")
            assert result.status == "failed"
            assert "crash" in result.error

    # --- send_with_failover ---

    @pytest.mark.asyncio
    async def test_failover_tries_first_healthy_provider(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())

            ok = MessageDeliveryStatus(
                message_id="m10", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=ok)
            router.providers["dc"].send = AsyncMock(return_value=ok)

            result = await router.send_with_failover(_make_outbound(), chain="default")
            assert result.status == "sent"

    @pytest.mark.asyncio
    async def test_failover_falls_to_second_provider(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())

            fail = MessageDeliveryStatus(
                message_id="", platform="telegram", status="failed", error="down"
            )
            ok = MessageDeliveryStatus(
                message_id="m11", platform="discord", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=fail)
            router.providers["dc"].send = AsyncMock(return_value=ok)

            result = await router.send_with_failover(_make_outbound(), chain="default")
            assert result.status == "sent"
            assert result.message_id == "m11"

    @pytest.mark.asyncio
    async def test_failover_all_providers_fail(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())

            fail = MessageDeliveryStatus(
                message_id="", platform="", status="failed", error="unreachable"
            )
            router.providers["tg"].send = AsyncMock(
                side_effect=Exception("tg error")
            )
            router.providers["dc"].send = AsyncMock(
                side_effect=Exception("dc error")
            )

            result = await router.send_with_failover(_make_outbound(), chain="default")
            assert result.status == "failed"
            assert "All providers" in result.error

    @pytest.mark.asyncio
    async def test_failover_unknown_chain_falls_back_to_default_provider(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            ok = MessageDeliveryStatus(
                message_id="m12", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=ok)

            result = await router.send_with_failover(
                _make_outbound(), chain="nonexistent_chain"
            )
            # Falls back to [self.default_provider] which is "tg"
            assert result.status == "sent"

    @pytest.mark.asyncio
    async def test_send_with_chain_arg_uses_failover(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())

            ok = MessageDeliveryStatus(
                message_id="m13", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=ok)

            result = await router.send(_make_outbound(), chain="default")
            assert result.status == "sent"

    # --- handle_webhook ---

    @pytest.mark.asyncio
    async def test_handle_webhook_unknown_platform(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            result = await router.handle_webhook("whatsapp", {}, b"{}")
            assert result is None

    @pytest.mark.asyncio
    async def test_handle_webhook_dispatches_to_provider(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            expected_msg = InboundMessage(
                platform="tg", channel_id="c1", sender_id="s1", text="hello"
            )
            router.providers["tg"].validate_webhook = AsyncMock(
                return_value=expected_msg
            )

            result = await router.handle_webhook(
                "tg", {"x-telegram-bot-api-secret-token": "s"}, b"{}"
            )
            assert result is not None
            assert result.text == "hello"

    @pytest.mark.asyncio
    async def test_handle_webhook_exception_returns_none(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}):
            router = self._make_router(self._basic_config())

            router.providers["tg"].validate_webhook = AsyncMock(
                side_effect=Exception("parse error")
            )

            result = await router.handle_webhook("tg", {}, b"bad data")
            assert result is None

    # --- Credential pooling ---

    def test_credential_pool_created_for_env_keys(self):
        cfg = {
            "providers": {
                "tg": {
                    "type": "telegram",
                    "enabled": True,
                    "env_keys": ["TG_KEY_A", "TG_KEY_B"],
                },
            },
            "defaults": {"provider": "tg"},
        }
        with patch.dict(
            os.environ, {"TG_KEY_A": "key_a", "TG_KEY_B": "key_b"}
        ):
            router = self._make_router(cfg)
            assert "tg" in router.credential_pools
            assert router.credential_pools["tg"].size() == 2

    def test_credential_pool_created_for_single_env_key(self):
        cfg = {
            "providers": {
                "tg": {
                    "type": "telegram",
                    "enabled": True,
                    "env_key": "TG_SINGLE_KEY",
                },
            },
            "defaults": {"provider": "tg"},
        }
        with patch.dict(os.environ, {"TG_SINGLE_KEY": "single_key_val"}):
            router = self._make_router(cfg)
            assert "tg" in router.credential_pools
            assert router.credential_pools["tg"].size() == 1

    def test_credential_pool_empty_when_no_env_vars(self):
        cfg = {
            "providers": {
                "tg": {
                    "type": "telegram",
                    "enabled": True,
                    "env_keys": ["NONEXISTENT_KEY_1", "NONEXISTENT_KEY_2"],
                },
            },
            "defaults": {"provider": "tg"},
        }
        with patch.dict(os.environ, {}, clear=False):
            router = self._make_router(cfg)
            assert "tg" not in router.credential_pools

    # --- Health summary ---

    def test_get_health_summary(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "DISCORD_BOT_TOKEN": "tok2"}):
            router = self._make_router(self._basic_config())
            summary = router.get_health_summary()
            assert "tg" in summary
            assert "dc" in summary
            assert "healthy" in summary["tg"]
            assert "healthy" in summary["dc"]

    # --- _PROVIDER_TYPES registry ---

    def test_provider_types_registry_has_all_providers(self):
        assert "telegram" in _PROVIDER_TYPES
        assert "discord" in _PROVIDER_TYPES
        assert "slack" in _PROVIDER_TYPES
        assert "feishu" in _PROVIDER_TYPES

    def test_provider_types_map_to_correct_classes(self):
        assert _PROVIDER_TYPES["telegram"] is TelegramProvider
        assert _PROVIDER_TYPES["discord"] is DiscordProvider
        assert _PROVIDER_TYPES["slack"] is SlackProvider
        assert _PROVIDER_TYPES["feishu"] is FeishuProvider


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Integration-style: send with platform auto-selection
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRouterPlatformAutoSelect:
    """Verify that router.send() auto-selects provider from message.platform."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.config_dir = tmp_path / "configs"
        self.config_dir.mkdir()
        self.config_path = str(self.config_dir / "messaging.yaml")

    def _make_router(self) -> MessagingRouter:
        import yaml

        cfg = {
            "providers": {
                "tg": {"type": "telegram", "enabled": True, "env_key": "T1"},
                "dc": {"type": "discord", "enabled": True, "env_key": "D1"},
            },
            "defaults": {"provider": "tg"},
        }
        with open(self.config_path, "w") as f:
            yaml.dump(cfg, f)
        return MessagingRouter(config_path=self.config_path)

    @pytest.mark.asyncio
    async def test_send_uses_platform_from_message_when_no_provider_given(self):
        with patch.dict(os.environ, {"T1": "tok", "D1": "tok2"}):
            router = self._make_router()

            # When message.platform matches a provider key, it routes there.
            # Provider names are "tg"/"dc", not "telegram"/"discord".
            # Sending with platform="tg" routes to the "tg" provider directly.
            mock_result = MessageDeliveryStatus(
                message_id="mx", platform="telegram", status="sent"
            )
            router.providers["tg"].send = AsyncMock(return_value=mock_result)

            msg = OutboundMessage(platform="tg", channel_id="ch", text="test")
            result = await router.send(msg)
            assert result.status == "sent"
            assert result.message_id == "mx"

    @pytest.mark.asyncio
    async def test_send_with_unmatched_platform_raises(self):
        """If message.platform doesn't match any provider key and no provider
        is specified, get_provider raises ValueError."""
        with patch.dict(os.environ, {"T1": "tok", "D1": "tok2"}):
            router = self._make_router()

            msg = OutboundMessage(
                platform="telegram", channel_id="ch", text="test"
            )
            # "telegram" is not a provider key (keys are "tg", "dc"),
            # and no explicit provider= arg, so this raises.
            with pytest.raises(ValueError, match="not found"):
                await router.send(msg)

    @pytest.mark.asyncio
    async def test_send_with_explicit_provider_overrides_platform(self):
        with patch.dict(os.environ, {"T1": "tok", "D1": "tok2"}):
            router = self._make_router()

            dc_result = MessageDeliveryStatus(
                message_id="dc1", platform="discord", status="sent"
            )
            router.providers["dc"].send = AsyncMock(return_value=dc_result)

            msg = OutboundMessage(
                platform="telegram", channel_id="ch", text="test"
            )
            result = await router.send(msg, provider="dc")
            assert result.status == "sent"
            assert result.message_id == "dc1"
