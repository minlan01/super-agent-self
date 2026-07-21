"""Integration tests for agents API — status, messages, consensus.

Uses its own in-memory SQLite + RBAC seeding, independent of
test_agents_integration.py.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.db.models import Base
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


@pytest.fixture
def app_and_client():
    _prev_require_auth = os.environ.get("REQUIRE_AUTH")
    os.environ["REQUIRE_AUTH"] = "1"
    clear_settings_cache()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    RBACRepository.seed_default_roles_and_permissions(db)
    db.commit()

    from packages.db.session import get_db
    from apps.api_server.main import app

    def _override_get_db():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    yield client, db

    app.dependency_overrides.clear()
    db.close()
    if _prev_require_auth is not None:
        os.environ["REQUIRE_AUTH"] = _prev_require_auth
    else:
        os.environ.pop("REQUIRE_AUTH", None)


@pytest.fixture
def admin_token(app_and_client):
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"
    db.commit()
    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()
    return create_access_token({"sub": user.id, "username": user.username})


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _reset_agent_bus():
    """Reset the agent bus singleton so tests do not leak state."""
    import packages.agent_core.agent_bus as bus_mod
    bus_mod._bus = None


# ── Auth guard tests ─────────────────────────────────────────────────────


class TestAgentsAuth:
    """All agents endpoints require authentication when REQUIRE_AUTH=1."""

    @pytest.mark.integration
    def test_status_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/status")
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_messages_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/messages")
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_consensus_propose_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "p1",
                "proposer": "a1",
                "question": "Q?",
                "options": ["A", "B"],
            },
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_consensus_vote_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/vote",
            json={"proposal_id": "p1", "voter": "a1", "choice": "A"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_consensus_result_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/consensus/p1")
        assert resp.status_code in (401, 403)


# ── GET /agents/status ──────────────────────────────────────────────────


class TestAgentStatus:
    @pytest.mark.integration
    def test_status_returns_success(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/status", headers=_auth(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "data" in data


# ── GET /agents/messages ────────────────────────────────────────────────


class TestAgentMessages:
    @pytest.mark.integration
    def test_messages_default_limit(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/messages", headers=_auth(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"]["messages"], list)

    @pytest.mark.integration
    def test_messages_with_custom_limit(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.get(
            "/api/v1/agents/messages?limit=10",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"]["messages"], list)

    @pytest.mark.integration
    def test_messages_after_consensus_proposal(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        # Create a proposal — this sends a broadcast message on the bus
        client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "msg-test-1",
                "proposer": "agent-1",
                "question": "Pick one",
                "options": ["A", "B"],
            },
            headers=_auth(admin_token),
        )
        # Messages log should now contain the broadcast
        resp = client.get("/api/v1/agents/messages", headers=_auth(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        messages = data["data"]["messages"]
        assert len(messages) >= 1
        # The broadcast message from propose_consensus
        found = any(m["sender"] == "agent-1" for m in messages)
        assert found, "Expected a broadcast message from agent-1"


# ── POST /agents/consensus/propose ──────────────────────────────────────


class TestConsensusPropose:
    @pytest.mark.integration
    def test_propose_success(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "prop-1",
                "proposer": "agent-1",
                "question": "Which approach?",
                "options": ["A", "B"],
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "prop-1" in data["message"]

    @pytest.mark.integration
    def test_propose_validation_empty_options(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "prop-bad",
                "proposer": "agent-1",
                "question": "Q?",
                "options": ["only_one"],
            },
            headers=_auth(admin_token),
        )
        # min_length=2 on options field
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_propose_validation_empty_fields(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "",
                "proposer": "",
                "question": "",
                "options": ["A", "B"],
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422


# ── POST /agents/consensus/vote ─────────────────────────────────────────


class TestConsensusVote:
    @pytest.mark.integration
    def test_vote_success(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        # Create proposal first
        client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "vote-1",
                "proposer": "agent-1",
                "question": "Pick",
                "options": ["A", "B"],
            },
            headers=_auth(admin_token),
        )
        # Cast vote
        resp = client.post(
            "/api/v1/agents/consensus/vote",
            json={"proposal_id": "vote-1", "voter": "agent-2", "choice": "A"},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @pytest.mark.integration
    def test_vote_validation_empty_fields(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/vote",
            json={"proposal_id": "", "voter": "", "choice": ""},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422


# ── GET /agents/consensus/{proposal_id} ─────────────────────────────────


class TestConsensusResult:
    @pytest.mark.integration
    def test_result_no_votes(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        # Create proposal but do not vote
        client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "result-1",
                "proposer": "agent-1",
                "question": "Pick",
                "options": ["X", "Y"],
            },
            headers=_auth(admin_token),
        )
        resp = client.get(
            "/api/v1/agents/consensus/result-1",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["proposal_id"] == "result-1"
        assert data["data"]["status"] == "no_votes"
        assert data["data"]["winner"] is None

    @pytest.mark.integration
    def test_result_with_majority(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        # Propose
        client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "result-2",
                "proposer": "agent-1",
                "question": "Choose",
                "options": ["X", "Y"],
            },
            headers=_auth(admin_token),
        )
        # 2 votes for X, 1 for Y — X has majority
        for voter, choice in [("a1", "X"), ("a2", "X"), ("a3", "Y")]:
            client.post(
                "/api/v1/agents/consensus/vote",
                json={"proposal_id": "result-2", "voter": voter, "choice": choice},
                headers=_auth(admin_token),
            )
        resp = client.get(
            "/api/v1/agents/consensus/result-2",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["status"] == "decided"
        assert data["data"]["winner"] == "X"
        assert data["data"]["votes"] == 2
        assert data["data"]["total"] == 3

    @pytest.mark.integration
    def test_result_no_majority(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        # Propose with 3 options
        client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "result-3",
                "proposer": "agent-1",
                "question": "Choose",
                "options": ["A", "B", "C"],
            },
            headers=_auth(admin_token),
        )
        # 1 vote each — no majority (> total/2 requires > 1.5)
        for voter, choice in [("a1", "A"), ("a2", "B"), ("a3", "C")]:
            client.post(
                "/api/v1/agents/consensus/vote",
                json={"proposal_id": "result-3", "voter": voter, "choice": choice},
                headers=_auth(admin_token),
            )
        resp = client.get(
            "/api/v1/agents/consensus/result-3",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        # A gets most_common(1) with 1 vote, total=3, 1 <= 3/2 so no_majority
        assert data["data"]["status"] == "no_majority"

    @pytest.mark.integration
    def test_result_nonexistent_proposal(self, app_and_client, admin_token):
        _reset_agent_bus()
        client, _ = app_and_client
        resp = client.get(
            "/api/v1/agents/consensus/nonexistent-id",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["status"] == "no_votes"
