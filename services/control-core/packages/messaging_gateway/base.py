"""Abstract base provider for multi-platform messaging gateway."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    """Normalized representation of an incoming message from any platform."""

    platform: str  # "telegram" | "discord" | "slack" | "feishu"
    channel_id: str  # Platform-specific channel/chat/group ID
    sender_id: str  # Sender's platform-specific ID
    text: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    thread_id: str | None = None


@dataclass
class OutboundMessage:
    """A message to be sent to an external messaging platform."""

    platform: str
    channel_id: str
    text: str
    parse_mode: str = "plain"  # "plain" | "markdown" | "html"
    reply_to: str | None = None  # Message/thread ID to reply to
    attachments: list[dict[str, Any]] | None = None


@dataclass
class MessageDeliveryStatus:
    """Status of an outbound message delivery attempt."""

    message_id: str
    platform: str
    status: str  # "sent" | "delivered" | "failed"
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


class BaseMessagingProvider(ABC):
    """Abstract base class for messaging platform providers.

    Each provider implements sending, webhook validation, and health checking
    for a specific messaging platform (Telegram, Discord, Slack, Feishu).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.name: str = config.get("name", "unknown")

    @abstractmethod
    async def send(self, message: OutboundMessage) -> MessageDeliveryStatus:
        """Send an outbound message to the platform."""
        ...

    @abstractmethod
    async def validate_webhook(
        self, headers: dict[str, str], body: bytes
    ) -> InboundMessage | None:
        """Parse and validate an inbound webhook payload.

        Returns ``None`` if signature verification fails.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Lightweight connectivity test — returns True if the platform is reachable."""
        ...

    async def close(self) -> None:
        """Release resources (HTTP clients, etc.). Default is no-op."""
        pass
