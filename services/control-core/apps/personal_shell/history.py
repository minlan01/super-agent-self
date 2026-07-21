"""Chat history — persists conversations via ConversationRepository."""

from __future__ import annotations

import logging
from typing import Any

from rich.console import Console
from rich.table import Table

from packages.db.session import SessionLocal

logger = logging.getLogger(__name__)
console = Console()


class ChatHistory:
    """Manages a single conversation session with persistence.

    Wraps ``ConversationRepository`` to provide:
    - Automatic conversation creation on first message
    - Persistent message storage (user + assistant turns)
    - Session listing and search
    """

    def __init__(self, user_id: str = "default", edition: str = "personal") -> None:
        self.user_id = user_id
        self.edition = edition
        self.conversation_id: str | None = None
        self._local_messages: list[dict[str, str]] = []

    def _ensure_conversation(self) -> None:
        """Create a conversation record if one doesn't exist yet."""
        if self.conversation_id is not None:
            return

        from packages.db.repositories.conversation_repo import ConversationRepository

        db = SessionLocal()
        try:
            conv = ConversationRepository.create_conversation(
                db, user_id=self.user_id, edition=self.edition
            )
            db.commit()
            self.conversation_id = conv.id
        except Exception as e:
            db.rollback()
            logger.warning("Failed to create conversation: %s", e)
        finally:
            db.close()

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the local buffer and persist to DB."""
        self._local_messages.append({"role": role, "content": content})

        self._ensure_conversation()
        if self.conversation_id is None:
            return

        from packages.db.repositories.conversation_repo import ConversationRepository

        db = SessionLocal()
        try:
            ConversationRepository.add_message(
                db, self.conversation_id, role, content
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("Failed to persist message: %s", e)
        finally:
            db.close()

    @property
    def messages(self) -> list[dict[str, str]]:
        """Return the in-memory message list for the current session."""
        return self._local_messages

    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent conversation sessions for the current user."""
        from packages.db.repositories.conversation_repo import ConversationRepository

        db = SessionLocal()
        try:
            convs = ConversationRepository.list_conversations(
                db, user_id=self.user_id, limit=limit
            )
            return [
                {
                    "id": c.id,
                    "title": c.title or "(untitled)",
                    "edition": c.edition.value if hasattr(c.edition, "value") else c.edition,
                    "message_count": len(c.messages),
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in convs
            ]
        finally:
            db.close()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search across all conversations for the given query."""
        from packages.db.repositories.conversation_repo import ConversationRepository

        db = SessionLocal()
        try:
            return ConversationRepository.search_messages(db, query, limit=limit)
        finally:
            db.close()

    def display_sessions(self, limit: int = 10) -> None:
        """Display recent sessions as a rich table."""
        sessions = self.list_sessions(limit=limit)
        if not sessions:
            console.print("[dim]No conversation sessions found.[/]")
            return

        table = Table(title="Recent Conversations")
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Title", style="cyan")
        table.add_column("Edition", style="green")
        table.add_column("Messages", justify="right")
        table.add_column("Created", style="dim")

        for s in sessions:
            table.add_row(
                s["id"][:8],
                s["title"],
                s["edition"],
                str(s["message_count"]),
                (s["created_at"] or "")[:16],
            )

        console.print(table)

    def display_search(self, query: str, limit: int = 5) -> None:
        """Display search results as a rich table."""
        results = self.search(query, limit=limit)
        if not results:
            console.print(f"[dim]No results for '{query}'.[/]")
            return

        table = Table(title=f"Search: {query}")
        table.add_column("Conv ID", style="dim", max_width=8)
        table.add_column("Role", style="green")
        table.add_column("Content", max_width=60)
        table.add_column("Date", style="dim")

        for r in results:
            content = r["content"][:80] + ("..." if len(r["content"]) > 80 else "")
            table.add_row(
                (r["conversation_id"] or "")[:8],
                r["role"],
                content,
                (r["created_at"] or "")[:16],
            )

        console.print(table)
