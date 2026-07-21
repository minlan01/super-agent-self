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
        finally:
            pass

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


class TestAgentsAuth:
    def test_status_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/status")
        assert resp.status_code in (401, 403)

    def test_messages_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/agents/messages")
        assert resp.status_code in (401, 403)


class TestAgentsEndpoints:
    def test_get_status(self, app_and_client, admin_token):
        client, _ = app_and_client
        resp = client.get(
            "/api/v1/agents/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_get_messages(self, app_and_client, admin_token):
        client, _ = app_and_client
        resp = client.get(
            "/api/v1/agents/messages",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"]["messages"], list)

    def test_consensus_propose(self, app_and_client, admin_token):
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "test-1",
                "proposer": "agent-1",
                "question": "Which approach?",
                "options": ["A", "B"],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    def test_consensus_vote_and_result(self, app_and_client, admin_token):
        client, _ = app_and_client

        # Propose
        client.post(
            "/api/v1/agents/consensus/propose",
            json={
                "proposal_id": "test-2",
                "proposer": "agent-1",
                "question": "Choose",
                "options": ["X", "Y"],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Vote
        client.post(
            "/api/v1/agents/consensus/vote",
            json={"proposal_id": "test-2", "voter": "agent-1", "choice": "X"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client.post(
            "/api/v1/agents/consensus/vote",
            json={"proposal_id": "test-2", "voter": "agent-2", "choice": "X"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Get result
        resp = client.get(
            "/api/v1/agents/consensus/test-2",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["winner"] == "X"
        assert data["data"]["status"] == "decided"
