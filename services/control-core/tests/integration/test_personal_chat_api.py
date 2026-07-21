"""Integration tests for Personal Edition APIs — reminders, context, chat, editions."""

import pytest
from fastapi.testclient import TestClient

from apps.api_server.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.integration
class TestPersonalAPI:
    def test_create_reminder(self, client: TestClient):
        resp = client.post("/api/v1/personal/reminders", json={
            "title": "Buy groceries",
            "description": "Milk, eggs, bread",
        })
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["success"] is True
        assert "id" in body["data"]

    def test_list_reminders(self, client: TestClient):
        # Create first
        client.post("/api/v1/personal/reminders", json={"title": "Test reminder"})
        resp = client.get("/api/v1/personal/reminders")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) >= 1

    def test_dismiss_reminder(self, client: TestClient):
        create_resp = client.post("/api/v1/personal/reminders", json={"title": "Temp reminder"})
        reminder_id = create_resp.json()["data"]["id"]
        resp = client.post(f"/api/v1/personal/reminders/{reminder_id}/dismiss")
        assert resp.status_code == 200

    def test_get_daily_context(self, client: TestClient):
        resp = client.get("/api/v1/personal/context")
        assert resp.status_code == 200
        body = resp.json()
        assert "daily_context" in body["data"]
        assert "reminders" in body["data"]

    def test_get_preferences(self, client: TestClient):
        resp = client.get("/api/v1/personal/preferences")
        assert resp.status_code == 200

    def test_save_preference(self, client: TestClient):
        resp = client.post("/api/v1/personal/preferences", json={
            "key": "language",
            "value": "Python",
        })
        assert resp.status_code == 200


@pytest.mark.integration
class TestChatAPI:
    def test_reminder_intent(self, client: TestClient):
        resp = client.post("/api/v1/chat", json={
            "message": "Remind me to check the deploy tomorrow",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "reminder_created"
        assert "reminder" in body["reply"].lower() or "saved" in body["reply"].lower()

    def test_task_intent(self, client: TestClient):
        resp = client.post("/api/v1/chat", json={
            "message": "Open example.com and extract text",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "task_created"
        assert body["task_id"] is not None

    def test_preference_intent(self, client: TestClient):
        resp = client.post("/api/v1/chat", json={
            "message": "I prefer dark mode",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "preference_saved"

    def test_general_info(self, client: TestClient):
        resp = client.post("/api/v1/chat", json={
            "message": "Hello, what can you do?",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "none"
        # Response comes from LLM (or mock provider in tests), just verify non-empty
        assert len(body["reply"]) > 0


@pytest.mark.integration
class TestEditionsAPI:
    def test_list_editions(self, client: TestClient):
        resp = client.get("/api/v1/editions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) >= 2

    def test_get_enterprise_edition(self, client: TestClient):
        resp = client.get("/api/v1/editions/enterprise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["edition"] == "enterprise"

    def test_get_personal_edition(self, client: TestClient):
        resp = client.get("/api/v1/editions/personal")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["edition"] == "personal"

    def test_get_nonexistent_edition(self, client: TestClient):
        resp = client.get("/api/v1/editions/nonexistent")
        assert resp.status_code == 404
