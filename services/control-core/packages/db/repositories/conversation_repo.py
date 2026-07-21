"""Conversation repository — CRUD + full-text search for session messages."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from packages.db.models import Conversation, ConversationMessage


def _uuid() -> str:
    return str(uuid.uuid4())


class ConversationRepository:
    """Static methods for conversation and message persistence + search."""

    # ── Conversations ──────────────────────────────────────────────────────

    @staticmethod
    def create_conversation(
        db: Session, *, user_id: str = "default", title: str | None = None, edition: str = "enterprise"
    ) -> Conversation:
        conv = Conversation(
            id=_uuid(),
            user_id=user_id,
            title=title,
            edition=edition,
        )
        db.add(conv)
        db.flush()
        return conv

    @staticmethod
    def get_conversation(db: Session, conversation_id: str, message_limit: int = 500) -> Conversation | None:
        """Load a conversation with its most recent messages.

        *message_limit* controls how many messages to load (newest first,
        then reversed to chronological order).  Defaults to 500.
        """
        from sqlalchemy import select
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            return None
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(message_limit)
        )
        conv.messages = list(reversed(db.scalars(stmt).all()))
        return conv

    @staticmethod
    def list_conversations(
        db: Session, *, user_id: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[Conversation]:
        stmt = select(Conversation)
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)
        stmt = stmt.order_by(Conversation.created_at.desc()).offset(offset).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def count_conversations(db: Session, *, user_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(Conversation)
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)
        return db.scalar(stmt) or 0

    # ── Messages ───────────────────────────────────────────────────────────

    @staticmethod
    def add_message(
        db: Session,
        conversation_id: str,
        role: str,
        content: str,
    ) -> ConversationMessage:
        msg = ConversationMessage(
            id=_uuid(),
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        db.add(msg)
        db.flush()
        return msg

    @staticmethod
    def get_messages(
        db: Session, conversation_id: str, limit: int = 1000
    ) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_recent_messages(
        db: Session, conversation_id: str, limit: int = 20
    ) -> list[ConversationMessage]:
        """Return the most recent *limit* messages in chronological order.

        Performs ``ORDER BY created_at DESC LIMIT N`` at the SQL layer (instead
        of loading the entire conversation and slicing in Python), then
        reverses for chronological order.  Keeps per-request memory bounded.
        """
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        )
        return list(reversed(db.scalars(stmt).all()))

    # ── Search ─────────────────────────────────────────────────────────────

    @staticmethod
    def search_messages(
        db: Session,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-text search across all conversation messages.

        Uses SQL LIKE for SQLite compatibility (FTS5 requires separate setup).
        Returns list of dicts with message and conversation info.
        """
        safe_query = query.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{safe_query}%"
        stmt = (
            select(ConversationMessage, Conversation)
            .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
            .where(ConversationMessage.content.ilike(pattern, escape="\\"))
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        )
        results = db.execute(stmt).all()

        return [
            {
                "message_id": msg.id,
                "conversation_id": conv.id,
                "conversation_title": conv.title,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg, conv in results
        ]
