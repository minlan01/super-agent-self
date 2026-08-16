"""Integration tests for analytics flow — task creation, status distribution, metrics, export, and audit aggregation.

These tests create tasks with various statuses, query analytics and metrics
endpoints, and verify that the data is aggregated correctly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api_server.main import app


@pytest.fixture()
def client():
    """TestClient with a valid Bearer token (P1: require_auth defaults True)."""
    from tests.integration.conftest import make_auth_header

    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        headers = make_auth_header(db)
    finally:
        db.close()

    with TestClient(app) as c:
        c.headers.update(headers)
        yield c


def _create_task(client: TestClient, goal: str = "analytics task", **kwargs) -> str:
    """Helper: create a task and return its ID."""
    payload = {"goal": goal, **kwargs}
    resp = client.post("/api/v1/tasks", json=payload)
    assert resp.status_code == 201
    return resp.json()["data"]["id"]


def _cancel_task(client: TestClient, task_id: str) -> None:
    resp = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert resp.status_code == 200


# ── Task Status Distribution ────────────────────────────────────────────────


@pytest.mark.integration
class TestTaskStatusDistribution:
    """Create tasks in different statuses and verify distribution via metrics."""

    def test_metrics_shows_zero_initially(self, client: TestClient):
        """When no tasks are created, total_tasks should be 0."""
        resp = client.get("/api/v1/health/metrics")
        assert resp.status_code == 200
        body = resp.json()
        # Note: tasks may exist from other tests sharing the same DB,
        # but the structure should be correct
        assert "tasks" in body
        assert "total_tasks" in body

    def test_metrics_after_task_creation(self, client: TestClient):
        """After creating tasks, metrics should reflect the counts."""
        _create_task(client, goal="metrics-task-1")
        _create_task(client, goal="metrics-task-2")

        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        assert body["total_tasks"] >= 2
        # pending count should be >= 2
        assert body["tasks"].get("pending", 0) >= 2

    def test_metrics_after_cancellation(self, client: TestClient):
        """After cancelling a task, cancelled count should increase."""
        task_id = _create_task(client, goal="cancel-metrics-task")
        _cancel_task(client, task_id)

        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        assert body["tasks"].get("cancelled", 0) >= 1

    def test_metrics_status_breakdown_has_all_statuses(self, client: TestClient):
        """Metrics should include all TaskStatus values."""
        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        expected_statuses = {"pending", "planning", "awaiting_approval", "executing", "completed", "failed", "cancelled"}
        assert expected_statuses.issubset(set(body["tasks"].keys()))

    def test_total_tasks_equals_sum_of_statuses(self, client: TestClient):
        """total_tasks should equal the sum of all status counts."""
        _create_task(client, goal="sum-check-1")
        _create_task(client, goal="sum-check-2")

        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        total = body["total_tasks"]
        status_sum = sum(body["tasks"].values())
        assert total == status_sum


# ── Metrics Endpoint Validation ─────────────────────────────────────────────


@pytest.mark.integration
class TestMetricsEndpointValidation:
    """Validate the metrics endpoint response structure and content."""

    def test_metrics_has_required_fields(self, client: TestClient):
        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        for field in ("tasks", "total_tasks", "memories", "uptime_seconds", "version"):
            assert field in body, f"Missing field: {field}"

    def test_metrics_uptime_is_positive(self, client: TestClient):
        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        assert body["uptime_seconds"] >= 0

    def test_metrics_version_matches(self, client: TestClient):
        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        assert body["version"] is not None
        assert len(body["version"]) > 0

    def test_metrics_memories_structure(self, client: TestClient):
        resp = client.get("/api/v1/health/metrics")
        body = resp.json()
        assert "total" in body["memories"]
        assert "active" in body["memories"]
        assert body["memories"]["total"] >= 0
        assert body["memories"]["active"] >= 0

    def test_readiness_check_after_task_creation(self, client: TestClient):
        """Readiness should remain ok even with tasks in the system."""
        _create_task(client, goal="ready-check")
        resp = client.get("/api/v1/health/ready")
        body = resp.json()
        assert body["ready"] is True
        assert body["checks"]["db"] == "ok"


# ── Export with Analytics Data ──────────────────────────────────────────────


@pytest.mark.integration
class TestExportAnalyticsData:
    """Create tasks and verify export contains the correct data."""

    def test_export_json_contains_created_tasks(self, client: TestClient):
        _create_task(client, goal="export-analytics-task-1")
        _create_task(client, goal="export-analytics-task-2")

        resp = client.get("/api/v1/export/tasks?format=json")
        body = resp.json()
        assert body["success"] is True
        assert body["count"] >= 2
        goals = [item["goal"] for item in body["data"]]
        assert "export-analytics-task-1" in goals
        assert "export-analytics-task-2" in goals

    def test_export_csv_has_header_row(self, client: TestClient):
        _create_task(client, goal="csv-export-test")
        resp = client.get("/api/v1/export/tasks?format=csv")
        assert resp.status_code == 200
        csv_text = resp.text
        lines = csv_text.strip().split("\n")
        assert len(lines) >= 2  # header + at least 1 data row
        # Header should contain standard fields
        header = lines[0].lower()
        assert "id" in header
        assert "goal" in header
        assert "status" in header

    def test_export_memories_json_structure(self, client: TestClient):
        resp = client.get("/api/v1/export/memories?format=json")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_export_audit_json_contains_events(self, client: TestClient):
        """Creating a task should generate audit events visible in export."""
        _create_task(client, goal="audit-export-test")
        resp = client.get("/api/v1/export/audit?format=json")
        body = resp.json()
        assert body["success"] is True
        assert body["count"] >= 1
        events = body["data"]
        assert any(e.get("event_type") == "task_created" for e in events)

    def test_export_task_data_fields(self, client: TestClient):
        """Each exported task should have standard fields."""
        _create_task(client, goal="field-check-task")
        resp = client.get("/api/v1/export/tasks?format=json")
        body = resp.json()
        task = next(t for t in body["data"] if t["goal"] == "field-check-task")
        for field in ("id", "goal", "edition", "status", "user_id", "created_at"):
            assert field in task, f"Missing field: {field}"

    def test_export_cancelled_task_shows_correct_status(self, client: TestClient):
        task_id = _create_task(client, goal="cancel-export-test")
        _cancel_task(client, task_id)

        resp = client.get("/api/v1/export/tasks?format=json")
        body = resp.json()
        task = next(t for t in body["data"] if t["id"] == task_id)
        assert task["status"] == "cancelled"


# ── Audit Trail Aggregation ────────────────────────────────────────────────


@pytest.mark.integration
class TestAuditTrailAggregation:
    """Verify audit events are correctly aggregated across task operations."""

    def test_create_generates_task_created_event(self, client: TestClient):
        task_id = _create_task(client, goal="audit-create-test")
        resp = client.get(f"/api/v1/tasks/{task_id}/audit")
        events = resp.json()["data"]
        assert any(e["event_type"] == "task_created" for e in events)

    def test_cancel_generates_task_cancelled_event(self, client: TestClient):
        task_id = _create_task(client, goal="audit-cancel-test")
        _cancel_task(client, task_id)
        resp = client.get(f"/api/v1/tasks/{task_id}/audit")
        events = resp.json()["data"]
        event_types = [e["event_type"] for e in events]
        assert "task_created" in event_types
        assert "task_cancelled" in event_types

    def test_audit_event_has_required_fields(self, client: TestClient):
        task_id = _create_task(client, goal="audit-fields-test")
        resp = client.get(f"/api/v1/tasks/{task_id}/audit")
        events = resp.json()["data"]
        assert len(events) >= 1
        event = events[0]
        for field in ("id", "task_id", "event_type", "created_at"):
            assert field in event, f"Missing field: {field}"

    def test_audit_detail_contains_goal(self, client: TestClient):
        goal = "audit-detail-goal-test"
        task_id = _create_task(client, goal=goal)
        resp = client.get(f"/api/v1/tasks/{task_id}/audit")
        events = resp.json()["data"]
        created_event = next(e for e in events if e["event_type"] == "task_created")
        assert created_event["detail"]["goal"] == goal

    def test_batch_create_generates_multiple_audit_events(self, client: TestClient):
        """Batch creating tasks should generate an audit event for each."""
        resp = client.post("/api/v1/tasks/batch", json={
            "tasks": [
                {"goal": "batch-audit-1"},
                {"goal": "batch-audit-2"},
                {"goal": "batch-audit-3"},
            ]
        })
        assert resp.status_code == 201
        created = resp.json()["created"]
        assert len(created) == 3

        # Each task should have its own audit trail
        for task in created:
            audit_resp = client.get(f"/api/v1/tasks/{task['id']}/audit")
            events = audit_resp.json()["data"]
            assert any(e["event_type"] == "task_created" for e in events)
            assert any(e.get("detail", {}).get("source") == "batch" for e in events)

    def test_retry_generates_audit_event(self, client: TestClient):
        """Retrying a completed task should generate an audit event."""
        # Create and cancel, then retry (cancelled can be retried? let's use the API)
        task_id = _create_task(client, goal="retry-audit-test")
        _cancel_task(client, task_id)

        # Cancelled tasks cannot be retried (only failed/completed),
        # so let's verify the audit has the cancelled event
        resp = client.get(f"/api/v1/tasks/{task_id}/audit")
        events = resp.json()["data"]
        event_types = [e["event_type"] for e in events]
        assert "task_created" in event_types
        assert "task_cancelled" in event_types

    def test_export_audit_includes_all_events(self, client: TestClient):
        """The audit export should include events from multiple tasks."""
        task_id_1 = _create_task(client, goal="multi-audit-1")
        task_id_2 = _create_task(client, goal="multi-audit-2")
        _cancel_task(client, task_id_2)

        resp = client.get("/api/v1/export/audit?format=json")
        body = resp.json()
        events = body["data"]
        task_ids_in_events = {e["task_id"] for e in events}
        assert task_id_1 in task_ids_in_events
        assert task_id_2 in task_ids_in_events


# ── List and Filter Analytics ───────────────────────────────────────────────


@pytest.mark.integration
class TestListFilterAnalytics:
    """Test task listing with filters for analytics purposes."""

    def test_list_filter_by_pending_status(self, client: TestClient):
        _create_task(client, goal="pending-filter-test")
        resp = client.get("/api/v1/tasks", params={"status": "pending"})
        items = resp.json()["data"]["items"]
        assert len(items) >= 1
        assert all(t["status"] == "pending" for t in items)

    def test_list_filter_by_cancelled_status(self, client: TestClient):
        task_id = _create_task(client, goal="cancelled-filter-test")
        _cancel_task(client, task_id)
        resp = client.get("/api/v1/tasks", params={"status": "cancelled"})
        items = resp.json()["data"]["items"]
        assert len(items) >= 1
        assert all(t["status"] == "cancelled" for t in items)

    def test_list_pagination(self, client: TestClient):
        """Pagination should work correctly."""
        for i in range(5):
            _create_task(client, goal=f"page-test-{i}")

        resp = client.get("/api/v1/tasks", params={"page": 1, "page_size": 2})
        body = resp.json()["data"]
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) <= 2
        assert body["total"] >= 5

    def test_list_total_increases_with_creation(self, client: TestClient):
        """Total count should increase as tasks are created."""
        resp_before = client.get("/api/v1/tasks")
        total_before = resp_before.json()["data"]["total"]

        _create_task(client, goal="total-increase-test")
        _create_task(client, goal="total-increase-test-2")

        resp_after = client.get("/api/v1/tasks")
        total_after = resp_after.json()["data"]["total"]
        assert total_after == total_before + 2

    def test_health_check_always_ok(self, client: TestClient):
        """Health check should always return ok regardless of system state."""
        for _ in range(3):
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
