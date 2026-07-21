"""Slack Web API provider — send messages and validate webhooks.

Uses the Slack Web API via httpx. Webhook validation uses HMAC-SHA256
with the Signing Secret.
"""

from __future__ import annotations

import hashlib
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


class SlackProvider(BaseMessagingProvider):
    """Slack Web API messaging provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", "https://slack.com/api")
        env_keys = config.get("env_keys", [])
        self.api_key = ""
        self.signing_secret = ""
        for k in env_keys:
            val = os.environ.get(k, "")
            if val:
                if "SIGNING" in k.upper():
                    self.signing_secret = val
                else:
                    self.api_key = val
        if not self.api_key:
            self.api_key = os.environ.get(config.get("env_key", "SLACK_BOT_TOKEN"), "")
        self.timeout = config.get("timeout", 10)
        self._client: httpx.AsyncClient | None = None
        self._client_lock = threading.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url="https://slack.com/api/",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
        return self._client

    def _verify_signature(self, timestamp: str, body: str, signature: str) -> bool:
        """Verify Slack request signature using HMAC-SHA256."""
        if not self.signing_secret:
            logger.error(
                "Slack webhook: signing_secret not configured — "
                "rejecting all webhooks for safety"
            )
            return False

        sig_basestring = f"v0:{timestamp}:{body}"
        my_sig = (
            "v0="
            + hmac.HMAC(
                self.signing_secret.encode(),
                sig_basestring.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(my_sig, signature)

    async def send(self, message: OutboundMessage) -> MessageDeliveryStatus:
        client = await self._get_client()
        url = f"{self.base_url}/chat.postMessage"

        body: dict[str, Any] = {
            "channel": message.channel_id,
            "text": message.text,
        }
        if message.parse_mode == "markdown":
            body["mrkdwn"] = True
        if message.reply_to:
            body["thread_ts"] = message.reply_to

        try:
            resp = await client.post(url, json=body)
            data = resp.json()
        except Exception as e:
            return MessageDeliveryStatus(
                message_id="", platform="slack", status="failed", error=str(e)
            )

        if not data.get("ok"):
            error_msg = data.get("error", "Unknown error")
            return MessageDeliveryStatus(
                message_id="", platform="slack", status="failed", error=error_msg
            )

        ts = data.get("ts", "")
        return MessageDeliveryStatus(
                message_id=ts, platform="slack", status="sent"
            )

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_webhook(
        self, headers: dict[str, str], body: bytes
    ) -> InboundMessage | None:
        signature = headers.get("x-slack-signature", "")
        timestamp = headers.get("x-slack-request-timestamp", "")

        # Both headers are mandatory for validation
        if not signature or not timestamp:
            logger.warning(
                "Slack webhook: missing signature or timestamp headers"
            )
            return None

        # Check timestamp freshness
        try:
            if abs(time.time() - float(timestamp)) > 300:
                logger.warning("Slack webhook: timestamp too old")
                return None
        except ValueError:
            return None

        decoded_body = body.decode("utf-8", errors="replace")
        if not self._verify_signature(timestamp, decoded_body, signature):
            logger.warning("Slack webhook: signature verification failed")
            return None

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None

        # URL verification challenge
        if data.get("type") == "url_verification":
            logger.debug("Slack webhook: URL verification challenge")
            return None

        # Event subscription
        event = data.get("event", {})
        if event.get("type") not in ("message", "app_mention"):
            return None

        # Skip bot messages
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return None

        text = event.get("text", "")
        if not text:
            return None

        return InboundMessage(
            platform="slack",
            channel_id=event.get("channel", ""),
            sender_id=event.get("user", ""),
            text=text,
            raw_payload=data,
            thread_id=event.get("thread_ts"),
        )

    async def health_check(self) -> bool:
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/auth.test")
            data = resp.json()
            return data.get("ok", False)
        except Exception as e:
            logger.warning("Slack health check failed: %s", e)
            return False
