"""Multi-platform messaging gateway — provider abstraction, routing, and webhook handling.

Reuses the provider pattern from ``packages.llm_gateway``:
- ``BaseMessagingProvider`` (ABC) → concrete platform providers
- ``MessagingRouter`` → unified dispatch with health tracking and failover
- ``CredentialPool`` / ``ProviderHealthTracker`` imported from ``llm_gateway``
"""

from packages.messaging_gateway.base import (
    BaseMessagingProvider,
    InboundMessage,
    MessageDeliveryStatus,
    OutboundMessage,
)
from packages.messaging_gateway.messaging_router import MessagingRouter

__all__ = [
    "BaseMessagingProvider",
    "InboundMessage",
    "MessageDeliveryStatus",
    "MessagingRouter",
    "OutboundMessage",
]
