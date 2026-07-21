"""Unit tests for conversation API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api_server.routes.conversations import (
    delete_conversation,
    get_conversation,
    list_conversations,
)
from packages.db.models import Base, Conversation, ConversationMessage, UserRole
from packages.db.repositories.conversation_repo import ConversationRepository


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _make_admin_user() -> MagicMock:
    user = MagicMock()
    user.id = "admin-1"
    user.role = UserRole.ADMIN
    user.is_active = True
    return user


def _make_regular_user(user_id: str = "user-1") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = UserRole.USER
    user.is_active = True
    return user


def _seed_conversation(db: Session, user_id: str = "user-1", title: str | None = None) -> Conversation:
    conv = ConversationRepository.create_conversation(db, user_id=user_id, title=title)
    db.flush()
    return conv


def _seed_message(db: Session, conv_id: str, role: str = "user", content: str = "hello") -> ConversationMessage:
    msg = ConversationRepository.add_message(db, conv_id, role=role, content=content)
    db.flush()
    return msg


@pytest.mark.unit
class TestListConversations:
    def test_list_conversations_empty(self, db):
        result = list_conversations(limit=20, offset=0, db=db, current_user=_make_admin_user())
        assert result.data == []
        assert result.count == 0

    def test_list_conversations_with_data(self, db):
        _seed_conversation(db, user_id="user-1")
        _seed_conversation(db, user_id="user-1")
        result = list_conversations(limit=20, offset=0, db=db, current_user=_make_admin_user())
        assert result.count == 2
        assert len(result.data) == 2

    def test_list_conversations_filter_by_user(self, db):
        _seed_conversation(db, user_id="alice")
        _seed_conversation(db, user_id="bob")
        user = _make_regular_user("alice")
        result = list_conversations(limit=20, offset=0, db=db, current_user=user)
        assert result.count == 1
        assert result.data[0].user_id == "alice"

    def test_list_conversations_respects_limit(self, db):
        for i in range(5):
            _seed_conversation(db, user_id="user-1")
        result = list_conversations(limit=2, offset=0, db=db, current_user=_make_admin_user())
        assert len(result.data) == 2

    def test_list_conversations_requires_auth(self, db):
        with pytest.raises(HTTPException) as exc_info:
            list_conversations(limit=20, offset=0, db=db, current_user=None)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestGetConversation:
    def test_get_conversation_found(self, db):
        conv = _seed_conversation(db, user_id="user-1", title="Test")
        result = get_conversation(conversation_id=conv.id, db=db, current_user=_make_regular_user("user-1"))
        assert result.conversation.id == conv.id
        assert result.conversation.title == "Test"

    def test_get_conversation_not_found(self, db):
        with pytest.raises(HTTPException) as exc_info:
            get_conversation(conversation_id="nonexistent-id", db=db, current_user=_make_admin_user())
        assert exc_info.value.status_code == 404

    def test_get_conversation_with_messages(self, db):
        conv = _seed_conversation(db, user_id="user-1")
        _seed_message(db, conv.id, role="user", content="Hello")
        _seed_message(db, conv.id, role="assistant", content="Hi there!")

        result = get_conversation(conversation_id=conv.id, db=db, current_user=_make_regular_user("user-1"))
        assert len(result.messages) == 2
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.messages[1].role == "assistant"

    def test_get_conversation_empty_messages(self, db):
        conv = _seed_conversation(db, user_id="user-1")
        result = get_conversation(conversation_id=conv.id, db=db, current_user=_make_regular_user("user-1"))
        assert result.messages == []

    def test_get_conversation_requires_auth(self, db):
        conv = _seed_conversation(db, user_id="user-1")
        with pytest.raises(HTTPException) as exc_info:
            get_conversation(conversation_id=conv.id, db=db, current_user=None)
        assert exc_info.value.status_code == 401

    def test_get_conversation_owner_enforcement(self, db):
        conv = _seed_conversation(db, user_id="alice")
        other_user = _make_regular_user("bob")
        with pytest.raises(HTTPException) as exc_info:
            get_conversation(conversation_id=conv.id, db=db, current_user=other_user)
        assert exc_info.value.status_code == 403


@pytest.mark.unit
class TestDeleteConversation:
    def test_delete_conversation(self, db):
        conv = _seed_conversation(db, user_id="user-1")
        result = delete_conversation(conversation_id=conv.id, db=db, current_user=_make_regular_user("user-1"))
        assert result["success"] is True

        assert ConversationRepository.get_conversation(db, conv.id) is None

    def test_delete_conversation_not_found(self, db):
        with pytest.raises(HTTPException) as exc_info:
            delete_conversation(conversation_id="nonexistent-id", db=db, current_user=_make_admin_user())
        assert exc_info.value.status_code == 404

    def test_delete_conversation_removes_messages(self, db):
        conv = _seed_conversation(db, user_id="user-1")
        _seed_message(db, conv.id, role="user", content="will be deleted")
        _seed_message(db, conv.id, role="assistant", content="also deleted")

        delete_conversation(conversation_id=conv.id, db=db, current_user=_make_regular_user("user-1"))

        msgs = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv.id
        ).all()
        assert len(msgs) == 0

    def test_delete_conversation_requires_auth(self, db):
        conv = _seed_conversation(db, user_id="user-1")
        with pytest.raises(HTTPException) as exc_info:
            delete_conversation(conversation_id=conv.id, db=db, current_user=None)
        assert exc_info.value.status_code == 401

    def test_delete_conversation_owner_enforcement(self, db):
        conv = _seed_conversation(db, user_id="alice")
        other_user = _make_regular_user("bob")
        with pytest.raises(HTTPException) as exc_info:
            delete_conversation(conversation_id=conv.id, db=db, current_user=other_user)
        assert exc_info.value.status_code == 403
