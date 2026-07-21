"""Agent Communication Bus — message passing between agents."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LOG = 500
_MAX_PROPOSALS = 200


class MessageType(str, Enum):
    TASK_REQUEST = "task_request"
    TASK_RESULT = "task_result"
    STATUS_UPDATE = "status_update"
    CONSENSUS_VOTE = "consensus_vote"
    BROADCAST = "broadcast"


@dataclass
class AgentMessage:
    """A message exchanged between agents."""
    sender: str
    recipient: str  # "*" for broadcast
    type: MessageType
    payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    correlation_id: str = ""


class AgentBus:
    """In-memory message bus for inter-agent communication."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = defaultdict(lambda: asyncio.Queue(maxsize=100))
        self._subscribers: dict[str, list[Any]] = defaultdict(list)
        self._message_log: list[AgentMessage] = []
        self._consensus_votes: dict[str, list[dict[str, Any]]] = {}
        self._consensus_options: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

    async def send(self, message: AgentMessage) -> bool:
        """Send a message to a specific agent or broadcast."""
        async with self._lock:
            self._message_log.append(message)
            if len(self._message_log) > _MAX_LOG * 2:
                self._message_log = self._message_log[-_MAX_LOG:]

        if message.recipient == "*":
            for queue in self._queues.values():
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass
            return True
        else:
            try:
                self._queues[message.recipient].put_nowait(message)
                return True
            except asyncio.QueueFull:
                logger.warning("Queue full for agent: %s", message.recipient)
                return False

    async def receive(self, agent_id: str, timeout: float = 1.0) -> AgentMessage | None:
        """Receive a message for an agent (with timeout)."""
        queue = self._queues[agent_id]
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def propose_consensus(self, proposal_id: str, proposer: str, question: str, options: list[str]) -> str:
        async with self._lock:
            if proposal_id in self._consensus_votes:
                raise ValueError(f"Proposal '{proposal_id}' already exists")
            self._consensus_votes[proposal_id] = []
            self._consensus_options[proposal_id] = list(options)
            if len(self._consensus_votes) > _MAX_PROPOSALS:
                oldest = list(self._consensus_votes.keys())[: len(self._consensus_votes) - _MAX_PROPOSALS]
                for k in oldest:
                    del self._consensus_votes[k]
                    self._consensus_options.pop(k, None)
        task = asyncio.ensure_future(self.send(AgentMessage(
            sender=proposer,
            recipient="*",
            type=MessageType.CONSENSUS_VOTE,
            payload={"proposal_id": proposal_id, "question": question, "options": options},
            correlation_id=proposal_id,
        )))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return proposal_id

    async def cast_vote(self, proposal_id: str, voter: str, choice: str) -> None:
        """Cast a vote on a consensus proposal (one vote per voter)."""
        async with self._lock:
            if proposal_id not in self._consensus_votes:
                raise ValueError(f"Proposal '{proposal_id}' not found")
            valid_options = self._consensus_options.get(proposal_id, [])
            if valid_options and choice not in valid_options:
                raise ValueError(f"Invalid choice '{choice}' for proposal '{proposal_id}'. Valid options: {valid_options}")
            votes = self._consensus_votes[proposal_id]
            for v in votes:
                if v["voter"] == voter:
                    return
            self._consensus_votes[proposal_id].append({"voter": voter, "choice": choice})

    async def get_consensus_result(self, proposal_id: str) -> dict[str, Any]:
        """Get the result of a consensus vote."""
        async with self._lock:
            votes = self._consensus_votes.get(proposal_id, [])
        if not votes:
            return {"proposal_id": proposal_id, "status": "no_votes", "winner": None}

        from collections import Counter
        tally = Counter(v["choice"] for v in votes)
        most_common = tally.most_common(1)
        if not most_common:
            return {"proposal_id": proposal_id, "status": "no_votes", "winner": None}

        winner, winner_count = most_common[0]
        total = len(votes)

        return {
            "proposal_id": proposal_id,
            "status": "decided" if winner_count > total / 2 else "no_majority",
            "winner": winner,
            "votes": winner_count,
            "total": total,
            "tally": dict(tally),
        }

    def get_message_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent messages for monitoring (snapshot, safe to call from any thread)."""
        # Take a slice copy to avoid iteration while another coroutine mutates
        snapshot = list(self._message_log[-limit:])
        return [
            {"sender": m.sender, "recipient": m.recipient, "type": m.type.value,
             "payload": m.payload, "timestamp": m.timestamp}
            for m in snapshot
        ]


# Singleton
_bus: AgentBus | None = None


def get_agent_bus() -> AgentBus:
    global _bus
    if _bus is None:
        _bus = AgentBus()
    return _bus
