"""Integration tests for the Task API."""

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api_server.main import app


@pytest.fixture()
def client():
    """Yield a TestClient — startup event creates DB tables automatically."""
    with TestClient(app) as c:
        yield c


# ── Health ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_health_check(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "edition" in body


# ── Create ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_create_task(client: TestClient):
    resp = client.post("/api/v1/tasks", json={"goal": "Run integration tests"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "pending"
    assert data["goal"] == "Run integration tests"
    assert "id" in data
    assert data["edition"] == "enterprise"


@pytest.mark.integration
def test_create_task_with_edition(client: TestClient):
    resp = client.post(
        "/api/v1/tasks",
        json={"goal": "Personal task", "edition": "personal"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["edition"] == "personal"


# ── List ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_list_tasks(client: TestClient):
    # Ensure at least one task exists
    client.post("/api/v1/tasks", json={"goal": "For list test"})

    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    pag = body["data"]
    assert "total" in pag
    assert "items" in pag
    assert pag["page"] == 1
    assert pag["page_size"] == 20
    assert isinstance(pag["items"], list)


@pytest.mark.integration
def test_list_tasks_filter_status(client: TestClient):
    create_resp = client.post("/api/v1/tasks", json={"goal": "Filter me"})
    task_id = create_resp.json()["data"]["id"]

    # Cancel so we can filter for cancelled
    client.post(f"/api/v1/tasks/{task_id}/cancel")

    resp = client.get("/api/v1/tasks", params={"status": "cancelled"})
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) >= 1
    assert all(item["status"] == "cancelled" for item in items)


# ── Detail ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_get_task_detail(client: TestClient):
    create_resp = client.post("/api/v1/tasks", json={"goal": "Detail test"})
    task_id = create_resp.json()["data"]["id"]

    resp = client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == task_id
    assert data["goal"] == "Detail test"
    assert data["steps"] == []


@pytest.mark.integration
def test_get_task_not_found(client: TestClient):
    fake_id = str(uuid.uuid4())
    resp = client.get(f"/api/v1/tasks/{fake_id}")
    assert resp.status_code == 404


# ── Cancel ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_cancel_task(client: TestClient):
    create_resp = client.post("/api/v1/tasks", json={"goal": "Cancel me"})
    task_id = create_resp.json()["data"]["id"]

    resp = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "cancelled"
    assert data["id"] == task_id


@pytest.mark.integration
def test_cancel_non_cancellable(client: TestClient):
    create_resp = client.post("/api/v1/tasks", json={"goal": "Double cancel"})
    task_id = create_resp.json()["data"]["id"]

    # First cancel should succeed
    first = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert first.status_code == 200

    # Second cancel should fail with 400
    second = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert second.status_code == 400


@pytest.mark.integration
def test_cancel_not_found(client: TestClient):
    fake_id = str(uuid.uuid4())
    resp = client.post(f"/api/v1/tasks/{fake_id}/cancel")
    assert resp.status_code == 404


# ── Steps ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_get_task_steps(client: TestClient):
    create_resp = client.post("/api/v1/tasks", json={"goal": "Steps test"})
    task_id = create_resp.json()["data"]["id"]

    resp = client.get(f"/api/v1/tasks/{task_id}/steps")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Audit ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_get_task_audit(client: TestClient):
    create_resp = client.post("/api/v1/tasks", json={"goal": "Audit test"})
    task_id = create_resp.json()["data"]["id"]

    resp = client.get(f"/api/v1/tasks/{task_id}/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    events = body["data"]
    assert len(events) >= 1
    assert any(e["event_type"] == "task_created" for e in events)


@pytest.mark.integration
def test_create_task_audit_trail(client: TestClient):
    goal = "Audit trail verification"
    resp = client.post("/api/v1/tasks", json={"goal": goal})
    task_id = resp.json()["data"]["id"]

    audit_resp = client.get(f"/api/v1/tasks/{task_id}/audit")
    events = audit_resp.json()["data"]

    created_events = [e for e in events if e["event_type"] == "task_created"]
    assert len(created_events) == 1
    assert created_events[0]["task_id"] == task_id
    assert created_events[0]["detail"]["goal"] == goal


# ── Full lifecycle ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_full_lifecycle(client: TestClient):
    # 1. Create
    create_resp = client.post("/api/v1/tasks", json={"goal": "Lifecycle test"})
    assert create_resp.status_code == 201
    task_id = create_resp.json()["data"]["id"]
    assert create_resp.json()["data"]["status"] == "pending"

    # 2. Get (verify pending)
    get_resp = client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["status"] == "pending"

    # 3. Cancel
    cancel_resp = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["data"]["status"] == "cancelled"

    # 4. Get again (verify cancelled)
    get_resp2 = client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp2.json()["data"]["status"] == "cancelled"

    # 5. Audit (expect task_created + task_cancelled = 2 events)
    audit_resp = client.get(f"/api/v1/tasks/{task_id}/audit")
    events = audit_resp.json()["data"]
    event_types = [e["event_type"] for e in events]
    assert "task_created" in event_types
    assert "task_cancelled" in event_types
    assert len(events) == 2
