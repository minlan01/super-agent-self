"""Multi-Agent API — agent status, communication, consensus."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any

from apps.api_server.dependencies import require_permission
from packages.agent_core.schemas import TaskExecutionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class ConsensusProposal(BaseModel):
    proposal_id: str = Field(..., min_length=1, max_length=100)
    proposer: str = Field(..., min_length=1, max_length=100)
    question: str = Field(..., min_length=1, max_length=1000)
    options: list[str] = Field(..., min_length=2, max_length=10)


class ConsensusVote(BaseModel):
    proposal_id: str = Field(..., min_length=1, max_length=100)
    voter: str = Field(..., min_length=1, max_length=100)
    choice: str = Field(..., min_length=1, max_length=200)


@router.get("/status", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "read"))])
async def get_agent_status() -> dict[str, Any]:
    """Get current multi-agent system status."""
    from packages.policy.unified_registry import tool_registry

    tools = tool_registry.list_tools()
    agent_tools = [t for t in tools if t.category == "agent"]

    return {
        "success": True,
        "data": {
            "agent_tools": [
                {"name": t.name, "description": t.description, "category": t.category}
                for t in agent_tools
            ],
            "delegation_enabled": any(t.name == "delegate.task" for t in agent_tools),
        },
    }


@router.get("/messages", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "read"))])
async def get_agent_messages(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """Get recent inter-agent messages."""
    from packages.agent_core.agent_bus import get_agent_bus

    bus = get_agent_bus()
    return {"success": True, "data": {"messages": bus.get_message_log(limit=limit)}}


@router.post("/consensus/propose", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "write"))])
async def create_consensus_proposal(body: ConsensusProposal) -> dict[str, Any]:
    """Create a new consensus proposal."""
    from packages.agent_core.agent_bus import get_agent_bus

    bus = get_agent_bus()
    try:
        await bus.propose_consensus(body.proposal_id, body.proposer, body.question, body.options)
    except ValueError as e:
        logger.warning("Consensus proposal rejected (%s): %s", body.proposal_id, e)
        raise HTTPException(status_code=409, detail="Proposal already exists or invalid")
    return {"success": True, "message": f"Proposal {body.proposal_id} created", "data": {"proposal_id": body.proposal_id}}


@router.post("/consensus/vote", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "write"))])
async def cast_consensus_vote(body: ConsensusVote) -> dict[str, Any]:
    """Cast a vote on a consensus proposal."""
    from packages.agent_core.agent_bus import get_agent_bus

    bus = get_agent_bus()
    try:
        await bus.cast_vote(body.proposal_id, body.voter, body.choice)
    except ValueError as e:
        logger.warning("Consensus vote rejected (%s/%s): %s", body.proposal_id, body.voter, e)
        raise HTTPException(status_code=400, detail="Invalid vote")
    return {"success": True, "message": "Vote cast", "data": {"proposal_id": body.proposal_id, "voter": body.voter, "choice": body.choice}}


@router.get("/consensus/{proposal_id}", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "read"))])
async def get_consensus_result(proposal_id: str) -> dict[str, Any]:
    """Get consensus vote result."""
    from packages.agent_core.agent_bus import get_agent_bus

    bus = get_agent_bus()
    result = await bus.get_consensus_result(proposal_id)
    return {"success": True, "data": result}
