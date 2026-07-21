"""Integration test — Chat flow: multi-turn conversation, intent classification, history."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import Base
from packages.db.repositories.conversation_repo import ConversationRepository


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


class TestConversationHistory:
    """Test multi-turn conversation persistence."""

    def test_create_conversation(self, db):
        conv = ConversationRepository.create_conversation(db, user_id="user-1", edition="personal")
        assert conv.id is not None
        assert conv.user_id == "user-1"
        assert conv.edition == "personal"

    def test_add_messages_to_conversation(self, db):
        conv = ConversationRepository.create_conversation(db, user_id="user-1")

        ConversationRepository.add_message(db, conv.id, role="user", content="Hello")
        ConversationRepository.add_message(db, conv.id, role="assistant", content="Hi there!")

        messages = ConversationRepository.get_messages(db, conv.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"

    def test_multi_turn_conversation(self, db):
        """Simulate a multi-turn conversation."""
        conv = ConversationRepository.create_conversation(
            db, user_id="user-1", title="Test Conversation",
        )

        # Turn 1
        ConversationRepository.add_message(db, conv.id, role="user", content="Search for AI news")
        ConversationRepository.add_message(db, conv.id, role="assistant", content="I'll search for AI news for you.")

        # Turn 2
        ConversationRepository.add_message(db, conv.id, role="user", content="Also save a summary")
        ConversationRepository.add_message(db, conv.id, role="assistant", content="Done! Summary saved.")

        messages = ConversationRepository.get_messages(db, conv.id)
        assert len(messages) == 4
        # Verify order
        assert messages[0].content == "Search for AI news"
        assert messages[3].content == "Done! Summary saved."

    def test_get_conversation_by_id(self, db):
        conv = ConversationRepository.create_conversation(db, user_id="user-1")
        found = ConversationRepository.get_conversation(db, conv.id)
        assert found is not None
        assert found.id == conv.id

    def test_get_nonexistent_conversation(self, db):
        found = ConversationRepository.get_conversation(db, "nonexistent-id")
        assert found is None

    def test_list_conversations(self, db):
        ConversationRepository.create_conversation(db, user_id="user-1")
        ConversationRepository.create_conversation(db, user_id="user-1")

        convs = ConversationRepository.list_conversations(db, user_id="user-1")
        assert len(convs) == 2

    def test_conversation_persists_across_sessions(self, db):
        """Verify that conversation history survives across session lookups."""
        conv = ConversationRepository.create_conversation(db, user_id="user-1")
        ConversationRepository.add_message(db, conv.id, role="user", content="First message")
        ConversationRepository.add_message(db, conv.id, role="assistant", content="First reply")

        # Simulate new session: look up existing conversation
        loaded = ConversationRepository.get_conversation(db, conv.id)
        assert loaded is not None

        # Continue the conversation
        ConversationRepository.add_message(db, loaded.id, role="user", content="Second message")
        ConversationRepository.add_message(db, loaded.id, role="assistant", content="Second reply")

        all_messages = ConversationRepository.get_messages(db, conv.id)
        assert len(all_messages) == 4


class TestIntentClassification:
    """Test keyword-based intent fallback (no LLM needed)."""

    def test_keyword_fallback_task(self):
        from apps.api_server.routes.chat import _keyword_fallback
        result = _keyword_fallback("search for weather today")
        assert result["intent"] == "task"

    def test_keyword_fallback_reminder(self):
        from apps.api_server.routes.chat import _keyword_fallback
        result = _keyword_fallback("remind me to call mom tomorrow")
        assert result["intent"] == "reminder"

    def test_keyword_fallback_preference(self):
        from apps.api_server.routes.chat import _keyword_fallback
        result = _keyword_fallback("I prefer dark mode always")
        assert result["intent"] == "preference"

    def test_keyword_fallback_info(self):
        from apps.api_server.routes.chat import _keyword_fallback
        result = _keyword_fallback("what is the weather like?")
        assert result["intent"] == "info"

    def test_keyword_chinese_task(self):
        from apps.api_server.routes.chat import _keyword_fallback
        result = _keyword_fallback("帮我查一下天气")
        assert result["intent"] == "task"

    def test_keyword_chinese_reminder(self):
        from apps.api_server.routes.chat import _keyword_fallback
        result = _keyword_fallback("提醒我明天开会")
        assert result["intent"] == "reminder"
