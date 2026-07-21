"""Telegram Bot API provider — send messages and validate webhooks.

Uses the Telegram Bot API via httpx. Webhook validation uses HMAC-SHA256
of the request body with the bot token as the secret key.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from typing import Any

import httpx

from packages.messaging_gateway.base import (
    BaseMessagingProvider,
    InboundMessage,
    MessageDeliveryStatus,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class TelegramProvider(BaseMessagingProvider):
    """Telegram Bot API messaging provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", "https://api.telegram.org")
        env_keys = config.get("env_keys", [])
        if env_keys:
            self.api_key = next(
                (os.environ.get(k, "") for k in env_keys if os.environ.get(k)), ""
            )
        else:
            self.api_key = os.environ.get(config.get("env_key", "TELEGRAM_BOT_TOKEN"), "")
        self.timeout = config.get("timeout", 10)
        self._client: httpx.AsyncClient | None = None
        self._client_lock = threading.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @property
    def _bot_url(self) -> str:
        return f"{self.base_url}/bot{self.api_key}"

    async def send(self, message: OutboundMessage) -> MessageDeliveryStatus:
        client = await self._get_client()
        url = f"{self._bot_url}/sendMessage"

        parse_mode = None
        if message.parse_mode == "markdown":
            parse_mode = "MarkdownV2"
        elif message.parse_mode == "html":
            parse_mode = "HTML"

        body: dict[str, Any] = {
            "chat_id": message.channel_id,
            "text": message.text,
        }
        if parse_mode:
            body["parse_mode"] = parse_mode
        if message.reply_to:
            body["reply_to_message_id"] = message.reply_to

        try:
            resp = await client.post(url, json=body)
            data = resp.json()
        except Exception as e:
            return MessageDeliveryStatus(
                message_id="", platform="telegram", status="failed", error=str(e)
            )

        if not data.get("ok"):
            error_desc = data.get("description", "Unknown error")
            return MessageDeliveryStatus(
                message_id="", platform="telegram", status="failed", error=error_desc
            )

        result = data.get("result", {})
        msg_id = str(result.get("message_id", ""))
        return MessageDeliveryStatus(
            message_id=msg_id, platform="telegram", status="sent"
        )

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_webhook(
        self, headers: dict[str, str], body: bytes
    ) -> InboundMessage | None:
        # Telegram validates via secret_token header set during setWebhook
        secret_token = headers.get("x-telegram-bot-api-secret-token", "")
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not expected:
            logger.error(
                "Telegram webhook: TELEGRAM_WEBHOOK_SECRET not configured — "
                "rejecting all webhooks for safety"
            )
            return None
        if not hmac.compare_digest(secret_token, expected):
            logger.warning("Telegram webhook: secret token mismatch")
            return None

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("Telegram webhook: invalid JSON body")
            return None

        message = data.get("message") or data.get("edited_message") or {}
        text = message.get("text", "")
        if not text:
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})

        return InboundMessage(
            platform="telegram",
            channel_id=str(chat.get("id", "")),
            sender_id=str(sender.get("id", "")),
            text=text,
            raw_payload=data,
            timestamp=message.get("date", time.time()),
            thread_id=str(message.get("message_thread_id", "")) or None,
        )

    async def health_check(self) -> bool:
        client = await self._get_client()
        try:
            resp = await client.get(f"{self._bot_url}/getMe")
            data = resp.json()
            return data.get("ok", False)
        except Exception as e:
            logger.warning("Telegram health check failed: %s", e)
            return False
