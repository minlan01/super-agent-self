"""Regression tests for task execution workspace and status ordering."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from apps.api_server.routes import tasks as task_routes
from packages.db.models import TaskStatus


def test_task_workspace_root_requires_canonical_uuid(tmp_path: Path):
    """Traversal and arbitrary directory names must be rejected."""

    with pytest.raises(HTTPException) as exc_info:
        task_routes._task_workspace_root(str(tmp_path), "../../outside")

    assert exc_info.value.status_code == 404
    assert not (tmp_path / ".." / "outside").exists()


@pytest.mark.asyncio
async def test_execute_rejects_invalid_id_before_status_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Invalid task IDs must not create workspaces or mutate task state."""

    calls: list[tuple[object, tuple, dict]] = []

    async def fake_run_async(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        raise AssertionError("status transition must not run")

    monkeypatch.setattr(task_routes, "run_async", fake_run_async)
    monkeypatch.setattr(
        task_routes,
        "get_settings",
        lambda: SimpleNamespace(workspace_root=str(tmp_path)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await task_routes.execute_task("not-a-uuid", SimpleNamespace(bind=object()))

    assert exc_info.value.status_code == 404
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_execute_uses_updated_task_and_contained_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Successful execution must use the transition result and safe workspace."""

    task_id = str(uuid4())
    workspace_root = tmp_path / "workspaces"
    updated_task = SimpleNamespace(
        id=task_id,
        goal="run safely",
        edition="enterprise",
        user_id="user-1",
        status=TaskStatus.PLANNING,
    )
    transition_calls: list[tuple] = []
    context_seen = []

    async def fake_run_async(func, *args, **kwargs):
        if func is task_routes.TaskRepository.atomic_status_transition:
            transition_calls.append((func, args, kwargs))
            return updated_task
        if func is task_routes.TaskRepository.get_steps:
            return []
        raise AssertionError(f"unexpected async repository function: {func}")

    class FakeOrchestrator:
        async def run(self, *, context, **kwargs):
            context_seen.append((context, kwargs))
            return {"status": "completed", "success": True, "results": []}

    monkeypatch.setattr(task_routes, "run_async", fake_run_async)
    monkeypatch.setattr(
        task_routes,
        "get_settings",
        lambda: SimpleNamespace(workspace_root=str(workspace_root)),
    )
    monkeypatch.setattr(task_routes, "get_orchestrator", lambda: FakeOrchestrator())

    response = await task_routes.execute_task(task_id, SimpleNamespace(bind=object()))

    expected_workspace = (workspace_root / task_id).resolve()
    assert expected_workspace.is_dir()
    assert transition_calls
    assert transition_calls[0][1][0] == task_id
    assert transition_calls[0][1][1:] == (
        TaskStatus.PENDING,
        TaskStatus.PLANNING,
    )
    assert context_seen[0][0].workspace_root == str(expected_workspace)
    assert context_seen[0][0].task_id == task_id
    assert response.data["task_id"] == task_id
    assert response.data["execution_success"] is True
