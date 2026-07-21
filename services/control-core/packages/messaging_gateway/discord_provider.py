"""Discord Bot API provider — send messages and validate webhooks.

Uses the Discord Bot API via httpx. Webhook validation uses Ed25519
signature verification on the request body.
"""

from __future__ import annotations

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


class DiscordProvider(BaseMessagingProvider):
    """Discord Bot API messaging provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", "https://discord.com/api/v10")
        env_keys = config.get("env_keys", [])
        if env_keys:
            self.api_key = next(
                (os.environ.get(k, "") for k in env_keys if os.environ.get(k)), ""
            )
        else:
            self.api_key = os.environ.get(config.get("env_key", "DISCORD_BOT_TOKEN"), "")
        self.timeout = config.get("timeout", 10)
        self._client: httpx.AsyncClient | None = None
        self._client_lock = threading.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=self.timeout,
                    headers={"Authorization": f"Bot {self.api_key}"},
                )
        return self._client

    async def send(self, message: OutboundMessage) -> MessageDeliveryStatus:
        client = await self._get_client()
        url = f"{self.base_url}/channels/{message.channel_id}/messages"

        body: dict[str, Any] = {"content": message.text}
        if message.parse_mode == "markdown":
            # Discord natively supports markdown
            pass
        if message.reply_to:
            body["message_reference"] = {"message_id": message.reply_to}

        try:
            resp = await client.post(url, json=body)
            data = resp.json()
        except Exception as e:
            return MessageDeliveryStatus(
                message_id="", platform="discord", status="failed", error=str(e)
            )

        if resp.status_code >= 400:
            error_msg = data.get("message", str(data))
            return MessageDeliveryStatus(
                message_id="", platform="discord", status="failed", error=error_msg
            )

        msg_id = data.get("id", "")
        return MessageDeliveryStatus(
            message_id=msg_id, platform="discord", status="sent"
        )

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_webhook(
        self, headers: dict[str, str], body: bytes
    ) -> InboundMessage | None:
        # Discord uses Ed25519 signatures for webhook authentication.
        # Full verification requires PyNaCl (nacl) library.
        # If nacl is not available, reject all Discord webhooks.
        signature = headers.get("x-signature-ed25519", "")
        timestamp = headers.get("x-signature-timestamp", "")

        if not signature or not timestamp:
            logger.warning("Discord webhook: missing signature headers")
            return None

        # Check timestamp freshness (5 min window)
        try:
            ts = float(timestamp)
            if abs(time.time() - ts) > 300:
                logger.warning("Discord webhook: timestamp too old")
                return None
        except ValueError:
            return None

        # Attempt Ed25519 signature verification
        try:
            from nacl.exceptions import BadSignatureError
            from nacl.signing import VerifyKey

            public_key = self.config.get("public_key", "")
            if not public_key:
                logger.error(
                    "Discord webhook: public_key not configured — "
                    "rejecting all webhooks"
                )
                return None

            verify_key = VerifyKey(public_key.encode("utf-8"))
            message = timestamp.encode("utf-8") + body
            verify_key.verify(message, bytes.fromhex(signature))
            logger.debug("Discord webhook: Ed25519 signature verified")
        except ImportError:
            # PyNaCl not installed — reject all webhooks for safety
            logger.error(
                "Discord webhook: PyNaCl not installed — "
                "cannot verify Ed25519 signatures, rejecting webhook"
            )
            return None
        except (BadSignatureError, Exception) as e:
            logger.warning(
                "Discord webhook: signature verification failed: %s", e
            )
            return None

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None

        # Handle interaction type 1 (PING) — respond with PONG
        if data.get("type") == 1:
            logger.debug("Discord webhook: PING received")
            return None

        # Extract message content from interaction or event
        text = ""
        channel_id = ""
        sender_id = ""

        # Slash command or message interaction
        if data.get("type") == 2:  # APPLICATION_COMMAND
            channel_id = data.get("channel_id", "")
            user = data.get("member", {}).get("user", data.get("user", {}))
            sender_id = user.get("id", "")
            options = data.get("data", {}).get("options", [])
            text = " ".join(opt.get("value", "") for opt in options) if options else ""
        elif "content" in data.get("d", {}):
            d = data["d"]
            text = d.get("content", "")
            channel_id = d.get("channel_id", "")
            author = d.get("author", {})
            sender_id = author.get("id", "")

        if not text:
            return None

        return InboundMessage(
            platform="discord",
            channel_id=channel_id,
            sender_id=sender_id,
            text=text,
            raw_payload=data,
        )

    async def health_check(self) -> bool:
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/users/@me")
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Discord health check failed: %s", e)
            return False
