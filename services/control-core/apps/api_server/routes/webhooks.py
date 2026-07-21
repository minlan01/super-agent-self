"""Webhook and messaging API routes — receive inbound webhooks, send messages, manage channels."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db, require_permission
from packages.agent_core.schemas import (
    ChannelCreateResponse,
    ChannelListResponse,
    MessageHistoryResponse,
    ResponseBase,
    SendMessageResponse,
    WebhookReceiveResponse,
)
from packages.db.models import User
from packages.db.repositories.messaging_repo import MessagingRepository
from packages.messaging_gateway.base import OutboundMessage
from packages.messaging_gateway.messaging_router import MessagingRouter

logger = logging.getLogger(__name__)

router = APIRouter()

_messaging_router_instance: MessagingRouter | None = None


def get_messaging_router() -> MessagingRouter:
    global _messaging_router_instance
    if _messaging_router_instance is None:
        _messaging_router_instance = MessagingRouter()
    return _messaging_router_instance


# ── Webhook endpoints (unauthenticated — verified by platform signatures) ────


# Allowed webhook platforms (whitelist)
_ALLOWED_PLATFORMS = {"telegram", "discord", "slack", "feishu"}

_MAX_WEBHOOK_BODY = 1024 * 1024  # 1 MB

_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie", "x-api-key",
    "x-forwarded-for", "x-real-ip",
})


@router.post("/webhooks/{platform}", response_model=WebhookReceiveResponse, summary="Receive platform webhook")
async def receive_webhook(platform: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Receive and validate an inbound webhook from a messaging platform.

    Platform-specific signature verification is handled by the provider.
    Only whitelisted platforms are accepted.
    """
    if platform not in _ALLOWED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unsupported webhook platform: {platform}")

    router_instance = get_messaging_router()
    body = await request.body()
    if len(body) > _MAX_WEBHOOK_BODY:
        raise HTTPException(status_code=413, detail="Webhook payload too large")

    safe_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _SENSITIVE_HEADERS
    }

    message = await router_instance.handle_webhook(platform, safe_headers, body)
    if message is None:
        # Feishu URL verification challenge needs a response
        import json
        try:
            data = json.loads(body)
            if data.get("type") == "url_verification":
                return {"challenge": data.get("challenge", "")}
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        raise HTTPException(
            status_code=400,
            detail="Webhook validation failed or no message content",
        )

    # Log the inbound message
    try:
        # Find or create a channel for this inbound message
        channels = MessagingRepository.list_channels_by_user(
            db, user_id=message.sender_id, platform=message.platform
        )
        channel_id = channels[0].id if channels else ""

        if channel_id:
            MessagingRepository.log_message(
                db,
                channel_id=channel_id,
                direction="inbound",
                platform=message.platform,
                sender_id=message.sender_id,
                content=message.text,
                status="received",
                raw_payload=message.raw_payload,
            )
    except Exception as e:
        logger.warning("Failed to log inbound message: %s", e)

    return {"success": True, "platform": platform, "sender": message.sender_id}


# ── Messaging API (authenticated) ───────────────────────────────────────────


class SendMessageRequest(BaseModel):
    platform: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    channel_id: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., max_length=5000)
    parse_mode: str = Field("plain", max_length=20, pattern=r"^[a-zA-Z0-9_\-]+$")
    reply_to: str | None = Field(None, max_length=200)


class CreateChannelRequest(BaseModel):
    platform: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    channel_id: str = Field(..., min_length=1, max_length=200)
    channel_name: str | None = Field(None, max_length=200)
    config: dict[str, Any] | None = Field(None, max_length=10000)


@router.post("/messaging/send", response_model=SendMessageResponse, summary="Send a message", dependencies=[Depends(require_permission("messaging", "write"))])
async def send_message(
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Send an outbound message to a messaging platform."""
    user_id = current_user.id if current_user else "default"
    router_instance = get_messaging_router()

    message = OutboundMessage(
        platform=req.platform,
        channel_id=req.channel_id,
        text=req.text,
        parse_mode=req.parse_mode,
        reply_to=req.reply_to,
    )

    result = await router_instance.send(message, provider=req.platform)

    # Log the outbound message
    try:
        channels = MessagingRepository.list_channels_by_user(
            db, user_id=user_id, platform=req.platform
        )
        if channels:
            MessagingRepository.log_message(
                db,
                channel_id=channels[0].id,
                direction="outbound",
                platform=req.platform,
                content=req.text,
                status=result.status,
            )
    except Exception as e:
        logger.warning("Failed to log outbound message: %s", e)

    return {
        "success": result.status == "sent",
        "message_id": result.message_id,
        "status": result.status,
    }


@router.get("/messaging/channels", response_model=ChannelListResponse, summary="List messaging channels", dependencies=[Depends(require_permission("messaging", "read"))])
def list_channels(
    platform: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List configured messaging channels for the current user."""
    user_id = current_user.id if current_user else "default"
    channels = MessagingRepository.list_channels_by_user(
        db, user_id=user_id, platform=platform
    )
    return {
        "success": True,
        "channels": [
            {
                "id": ch.id,
                "platform": ch.platform,
                "channel_id": ch.channel_id,
                "channel_name": ch.channel_name,
                "is_active": ch.is_active,
            }
            for ch in channels
        ],
    }


@router.post("/messaging/channels", response_model=ChannelCreateResponse, summary="Register a messaging channel", dependencies=[Depends(require_permission("messaging", "write"))])
def create_channel(
    req: CreateChannelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Register a new messaging channel for message routing."""
    user_id = current_user.id if current_user else "default"
    channel = MessagingRepository.create_channel(
        db,
        user_id=user_id,
        platform=req.platform,
        channel_id=req.channel_id,
        channel_name=req.channel_name,
        config=req.config,
    )
    return {
        "success": True,
        "channel": {
            "id": channel.id,
            "platform": channel.platform,
            "channel_id": channel.channel_id,
        },
    }


@router.get("/messaging/history/{channel_id}", response_model=MessageHistoryResponse, summary="Message history", dependencies=[Depends(require_permission("messaging", "read"))])
def message_history(
    channel_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get message history for a specific channel."""
    messages = MessagingRepository.get_message_history(
        db, channel_id, limit=limit, offset=offset
    )
    return {
        "success": True,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "platform": m.platform,
                "sender_id": m.sender_id,
                "content": m.content,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }
