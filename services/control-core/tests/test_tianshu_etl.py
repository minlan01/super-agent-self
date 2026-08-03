"""Tests for tianshu ETL (P3.6) — task transformation."""

import json
import os
import sys
import tempfile

import pytest

# Add scripts/etl to path for import.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "etl"))
from tianshu_etl import transform_task, run_etl


class TestTransformTask:
    def test_basic_transformation(self):
        tianshu = {
            "id": "TS-001",
            "title": "Test task",
            "state": "Done",
            "org": "汇总阁",
            "priority": "high",
            "output": "completed",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "updatedAt": "2026-01-02T00:00:00+00:00",
            "flow_log": [],
        }
        result = transform_task(tianshu)
        assert result["id"] == "TS-001"
        assert result["goal"] == "Test task"
        assert result["status"] == "completed"
        assert result["edition"] == "enterprise"
        assert result["tenant_id"] == "default"

    def test_state_mapping_all_states(self):
        """All 7 tianshu states map correctly."""
        for tianshu_state, expected in [
            ("Todo", "pending"),
            ("InProgress", "in_progress"),
            ("Blocked", "pending"),
            ("Review", "in_review"),
            ("Done", "completed"),
            ("Cancelled", "cancelled"),
            ("Failed", "failed"),
        ]:
            result = transform_task({"id": "x", "title": "t", "state": tianshu_state})
            assert result["status"] == expected, f"{tianshu_state} -> {result['status']}"

    def test_unknown_state_defaults_pending(self):
        result = transform_task({"id": "x", "title": "t", "state": "Weird"})
        assert result["status"] == "pending"

    def test_flow_log_dict_entries_become_steps(self):
        tianshu = {
            "id": "TS-002",
            "title": "Flow test",
            "state": "Done",
            "flow_log": [
                {"agent": "researcher", "input": {"q": "test"}, "output": "found", "status": "ok"},
                {"agent": "writer", "input": {"topic": "x"}, "output": "draft", "status": "ok"},
            ],
        }
        result = transform_task(tianshu)
        assert len(result["steps"]) == 2
        assert result["steps"][0]["tool_name"] == "researcher"
        assert result["steps"][1]["tool_name"] == "writer"

    def test_flow_log_string_entries(self):
        tianshu = {
            "id": "TS-003",
            "title": "String flow",
            "state": "Done",
            "flow_log": ["step 1", "step 2"],
        }
        result = transform_task(tianshu)
        assert len(result["steps"]) == 2
        assert result["steps"][0]["args"]["log"] == "step 1"

    def test_metadata_preserves_original_fields(self):
        tianshu = {
            "id": "TS-004",
            "title": "Meta test",
            "state": "Done",
            "org": "内阁",
            "priority": "urgent",
            "output": "done",
            "now": "advance",
            "block": "waiting",
        }
        result = transform_task(tianshu)
        meta = result["metadata"]
        assert meta["source"] == "tianshu"
        assert meta["original_org"] == "内阁"
        assert meta["original_priority"] == "urgent"

    def test_missing_id_gets_uuid(self):
        result = transform_task({"title": "no id", "state": "Todo"})
        assert result["id"]  # non-empty UUID
        assert len(result["id"]) >= 32  # UUID length

    def test_empty_flow_log(self):
        result = transform_task({"id": "x", "title": "t", "state": "Todo", "flow_log": []})
        assert result["steps"] == []


class TestRunETL:
    def test_dry_run(self):
        """Dry run produces summary without writing output."""
        # Use absolute path to the project root source file.
        repo_root = os.path.dirname(__file__) + "/../../.."
        source = os.path.realpath(os.path.join(repo_root, "scripts/etl/tianshu-tasks-source.json"))
        if not os.path.exists(source):
            pytest.skip("tianshu source not available in this env")
        result = run_etl(source, dry_run=True)
        assert result["dry_run"] is True
        assert result["tasks"] > 0

    def test_full_etl_writes_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = os.path.join(tmpdir, "source.json")
            output = os.path.join(tmpdir, "output.json")

            # Write test source.
            with open(source, "w") as f:
                json.dump([
                    {"id": "T1", "title": "Task 1", "state": "Done", "flow_log": []},
                    {"id": "T2", "title": "Task 2", "state": "Todo", "flow_log": []},
                ], f)

            result = run_etl(source, output, dry_run=False)
            assert result["tasks"] == 2
            assert os.path.exists(output)

            # Verify output content.
            with open(output) as f:
                tasks = json.load(f)
            assert len(tasks) == 2
            assert tasks[0]["status"] == "completed"
            assert tasks[1]["status"] == "pending"

    def test_missing_source_returns_error(self):
        result = run_etl("nonexistent.json", "out.json", dry_run=False)
        assert "error" in result
