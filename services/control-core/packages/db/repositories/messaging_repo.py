"""Repository for messaging channels and message logs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import MessageLog, MessagingChannel


class MessagingRepository:
    """Static methods for messaging channel and message log CRUD."""

    @staticmethod
    def create_channel(
        db: Session,
        *,
        user_id: str,
        platform: str,
        channel_id: str,
        channel_name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> MessagingChannel:
        channel = MessagingChannel(
            user_id=user_id,
            platform=platform,
            channel_id=channel_id,
            channel_name=channel_name,
            config=config,
        )
        db.add(channel)
        db.flush()
        db.refresh(channel)
        return channel

    @staticmethod
    def get_channel(db: Session, channel_id: str) -> MessagingChannel | None:
        stmt = select(MessagingChannel).where(MessagingChannel.id == channel_id)
        return db.scalar(stmt)

    @staticmethod
    def list_channels_by_user(
        db: Session, user_id: str, platform: str | None = None
    ) -> list[MessagingChannel]:
        stmt = select(MessagingChannel).where(MessagingChannel.user_id == user_id)
        if platform:
            stmt = stmt.where(MessagingChannel.platform == platform)
        stmt = stmt.order_by(MessagingChannel.created_at.desc())
        return list(db.scalars(stmt).all())

    @staticmethod
    def log_message(
        db: Session,
        *,
        channel_id: str,
        direction: str,
        platform: str,
        sender_id: str = "",
        content: str = "",
        status: str = "pending",
        raw_payload: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> MessageLog:
        entry = MessageLog(
            channel_id=channel_id,
            direction=direction,
            platform=platform,
            sender_id=sender_id,
            content=content,
            status=status,
            raw_payload=raw_payload,
            task_id=task_id,
        )
        db.add(entry)
        db.flush()
        db.refresh(entry)
        return entry

    @staticmethod
    def get_message_history(
        db: Session, channel_id: str, limit: int = 50, offset: int = 0
    ) -> list[MessageLog]:
        stmt = (
            select(MessageLog)
            .where(MessageLog.channel_id == channel_id)
            .order_by(MessageLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(stmt).all())
