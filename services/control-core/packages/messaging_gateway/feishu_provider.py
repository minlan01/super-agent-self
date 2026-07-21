"""Feishu (Lark) Open API provider — send messages and validate webhooks.

Uses the Feishu Open API via httpx. Webhook validation uses verification
token and event challenge. This is a stub implementation — full enterprise
verification requires app review approval.
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


class FeishuProvider(BaseMessagingProvider):
    """Feishu (Lark) Open API messaging provider."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", "https://open.feishu.cn/open-apis")
        env_keys = config.get("env_keys", [])
        self.app_id = ""
        self.app_secret = ""
        for k in env_keys:
            val = os.environ.get(k, "")
            if val:
                if "APP_ID" in k.upper():
                    self.app_id = val
                elif "APP_SECRET" in k.upper():
                    self.app_secret = val
        self.verification_token = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
        self.timeout = config.get("timeout", 10)
        self._client: httpx.AsyncClient | None = None
        self._client_lock = threading.Lock()
        self._tenant_token: str = ""
        self._token_expires: float = 0

    async def _get_client(self) -> httpx.AsyncClient:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _get_tenant_token(self) -> str:
        """Obtain or refresh the tenant_access_token."""
        if self._tenant_token and time.time() < self._token_expires:
            return self._tenant_token

        if not self.app_id or not self.app_secret:
            return ""

        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self.base_url}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                },
            )
            data = resp.json()
            self._tenant_token = data.get("tenant_access_token", "")
            expire = data.get("expire", 3600)
            self._token_expires = time.time() + expire - 60
            return self._tenant_token
        except Exception as e:
            logger.warning("Feishu: failed to get tenant token: %s", e)
            return ""

    async def send(self, message: OutboundMessage) -> MessageDeliveryStatus:
        token = await self._get_tenant_token()
        if not token:
            return MessageDeliveryStatus(
                message_id="",
                platform="feishu",
                status="failed",
                error="No tenant access token available — Feishu app may not be configured",
            )

        client = await self._get_client()
        url = f"{self.base_url}/im/v1/messages"

        body: dict[str, Any] = {
            "receive_id": message.channel_id,
            "msg_type": "text",
            "content": json.dumps({"text": message.text}),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            resp = await client.post(
                url, params={"receive_id_type": "chat_id"}, json=body, headers=headers
            )
            data = resp.json()
        except Exception as e:
            return MessageDeliveryStatus(
                message_id="", platform="feishu", status="failed", error=str(e)
            )

        code = data.get("code", -1)
        if code != 0:
            error_msg = data.get("msg", "Unknown error")
            return MessageDeliveryStatus(
                message_id="", platform="feishu", status="failed", error=error_msg
            )

        msg_id = data.get("data", {}).get("message_id", "")
        return MessageDeliveryStatus(
            message_id=msg_id, platform="feishu", status="sent"
        )

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_webhook(
        self, headers: dict[str, str], body: bytes
    ) -> InboundMessage | None:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None

        # URL verification challenge
        if data.get("type") == "url_verification":
            logger.debug("Feishu webhook: URL verification challenge")
            return None

        # Verify token — mandatory for security
        if not self.verification_token:
            logger.error(
                "Feishu webhook: verification_token not configured — "
                "rejecting all webhooks for safety"
            )
            return None

        event = data.get("header", data)
        token = event.get("token", "")
        if not hmac.compare_digest(token, self.verification_token):
            logger.warning("Feishu webhook: verification token mismatch")
            return None

        # Event callback
        event_data = data.get("event", {})
        msg = event_data.get("message", {})
        text = ""

        # Extract text content
        content_str = msg.get("content", "{}")
        try:
            content = json.loads(content_str) if isinstance(content_str, str) else content_str
            text = content.get("text", "")
        except json.JSONDecodeError:
            text = content_str

        if not text:
            return None

        return InboundMessage(
            platform="feishu",
            channel_id=msg.get("chat_id", ""),
            sender_id=event_data.get("sender", {}).get("sender_id", {}).get("user_id", ""),
            text=text,
            raw_payload=data,
            thread_id=msg.get("message_id"),
        )

    async def health_check(self) -> bool:
        token = await self._get_tenant_token()
        return bool(token)
