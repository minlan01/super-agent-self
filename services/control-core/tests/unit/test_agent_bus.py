import os
os.environ["TESTING"] = "1"

import asyncio
import pytest
from packages.agent_core.agent_bus import AgentBus, AgentMessage, MessageType, get_agent_bus


class TestAgentMessage:
    def test_create_message(self):
        msg = AgentMessage(
            sender="agent-1",
            recipient="agent-2",
            type=MessageType.TASK_REQUEST,
            payload={"task": "analyze"},
        )
        assert msg.sender == "agent-1"
        assert msg.recipient == "agent-2"
        assert msg.type == MessageType.TASK_REQUEST

    def test_broadcast_message(self):
        msg = AgentMessage(
            sender="agent-1",
            recipient="*",
            type=MessageType.BROADCAST,
            payload={"info": "hello"},
        )
        assert msg.recipient == "*"


class TestAgentBus:
    @pytest.mark.asyncio
    async def test_send_and_receive(self):
        bus = AgentBus()
        msg = AgentMessage(
            sender="agent-1",
            recipient="agent-2",
            type=MessageType.TASK_REQUEST,
            payload={"task": "do_something"},
        )
        assert await bus.send(msg) is True

    @pytest.mark.asyncio
    async def test_broadcast(self):
        bus = AgentBus()
        bus._queues["agent-1"] = asyncio.Queue(maxsize=100)
        bus._queues["agent-2"] = asyncio.Queue(maxsize=100)

        msg = AgentMessage(
            sender="coordinator",
            recipient="*",
            type=MessageType.BROADCAST,
            payload={"status": "start"},
        )
        assert await bus.send(msg) is True
        assert not bus._queues["agent-1"].empty()
        assert not bus._queues["agent-2"].empty()

    @pytest.mark.asyncio
    async def test_message_log(self):
        bus = AgentBus()
        for i in range(5):
            await bus.send(AgentMessage(
                sender=f"agent-{i}",
                recipient="target",
                type=MessageType.STATUS_UPDATE,
                payload={"n": i},
            ))
        log = bus.get_message_log(limit=3)
        assert len(log) == 3

    @pytest.mark.asyncio
    async def test_consensus_propose(self):
        bus = AgentBus()
        await bus.propose_consensus("prop-1", "agent-1", "Which approach?", ["A", "B", "C"])
        assert "prop-1" in bus._consensus_votes

    @pytest.mark.asyncio
    async def test_consensus_vote_and_result(self):
        bus = AgentBus()
        bus._consensus_votes["prop-2"] = []
        await bus.cast_vote("prop-2", "agent-1", "X")
        await bus.cast_vote("prop-2", "agent-2", "X")
        await bus.cast_vote("prop-2", "agent-3", "Y")

        result = await bus.get_consensus_result("prop-2")
        assert result["status"] == "decided"
        assert result["winner"] == "X"
        assert result["votes"] == 2
        assert result["total"] == 3

    @pytest.mark.asyncio
    async def test_consensus_no_majority(self):
        bus = AgentBus()
        bus._consensus_votes["prop-3"] = []
        await bus.cast_vote("prop-3", "agent-1", "A")
        await bus.cast_vote("prop-3", "agent-2", "B")

        result = await bus.get_consensus_result("prop-3")
        assert result["status"] == "no_majority"

    @pytest.mark.asyncio
    async def test_consensus_no_votes(self):
        bus = AgentBus()
        result = await bus.get_consensus_result("nonexistent")
        assert result["status"] == "no_votes"

    @pytest.mark.asyncio
    async def test_message_log_truncation(self):
        bus = AgentBus()
        for i in range(1100):
            await bus.send(AgentMessage(
                sender="s", recipient="r",
                type=MessageType.STATUS_UPDATE,
                payload={"i": i},
            ))
        assert len(bus._message_log) == 599


class TestGetAgentBus:
    def test_singleton(self):
        bus1 = get_agent_bus()
        bus2 = get_agent_bus()
        assert bus1 is bus2
