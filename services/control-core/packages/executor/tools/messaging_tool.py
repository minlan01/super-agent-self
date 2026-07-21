"""Messaging tool — send messages to external messaging platforms."""

from __future__ import annotations

import logging
from typing import Any

from packages.executor.tools.base import ToolBase, ToolResult
from packages.policy.unified_registry import tool_registry

logger = logging.getLogger(__name__)


def _messaging_check_fn(args: dict[str, Any]) -> tuple[bool, str]:
    """Pre-execution safety check for messaging tool."""
    platform = args.get("platform", "")
    allowed = {"telegram", "discord", "slack", "feishu"}
    if platform not in allowed:
        return False, f"Unknown platform '{platform}'. Allowed: {sorted(allowed)}"
    text = args.get("text", "")
    if not text.strip():
        return False, "Message text cannot be empty"
    if len(text) > 4096:
        return False, "Message text exceeds 4096 character limit"
    return True, ""


@tool_registry.register(
    category="messaging",
    risk_level="medium",
    emoji="💬",
    check_fn=_messaging_check_fn,
    params_schema={
        "type": "object",
        "required": ["platform", "channel_id", "text"],
        "properties": {
            "platform": {
                "type": "string",
                "description": "Target platform: telegram|discord|slack|feishu",
            },
            "channel_id": {
                "type": "string",
                "description": "Platform-specific channel/chat ID to send to",
            },
            "text": {
                "type": "string",
                "description": "Message text to send",
            },
            "parse_mode": {
                "type": "string",
                "description": "Format: plain|markdown|html",
                "default": "plain",
            },
            "reply_to": {
                "type": "string",
                "description": "Message/thread ID to reply to (optional)",
            },
        },
        "additionalProperties": False,
    },
)
class MessageSend(ToolBase):
    """Send a message to an external messaging platform."""

    name = "message.send"
    description = (
        "Send a message to an external messaging platform "
        "(Telegram, Discord, Slack, Feishu)"
    )

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        from packages.messaging_gateway.base import OutboundMessage

        platform = args.get("platform", "")
        channel_id = args.get("channel_id", "")
        text = args.get("text", "")
        parse_mode = args.get("parse_mode", "plain")
        reply_to = args.get("reply_to")

        try:
            from apps.api_server.routes.webhooks import get_messaging_router
            router = get_messaging_router()
        except Exception as e:
            return ToolResult(success=False, error=f"Messaging router unavailable: {e}")

        message = OutboundMessage(
            platform=platform,
            channel_id=channel_id,
            text=text,
            parse_mode=parse_mode,
            reply_to=reply_to,
        )

        try:
            result = await router.send(message, provider=platform)
            if result.status == "sent":
                return ToolResult(
                    success=True,
                    output=(
                        f"Message sent to {platform} "
                        f"(channel={channel_id}, msg_id={result.message_id})"
                    ),
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Message delivery failed: {result.error or result.status}",
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Messaging error: {e}")
