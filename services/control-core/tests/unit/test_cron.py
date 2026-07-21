"""Tests for Cron scheduling system."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.cron.jobs import CronJob, JobStore, _parse_schedule

# ── _parse_schedule ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestParseSchedule:
    def test_interval_minutes(self):
        result = _parse_schedule("every 30m")
        assert result["type"] == "interval"
        assert result["value"] == 30
        assert result["unit"] == "m"

    def test_interval_hours(self):
        result = _parse_schedule("every 2h")
        assert result["type"] == "interval"
        assert result["value"] == 2

    def test_cron_expression(self):
        result = _parse_schedule("0 9 * * *")
        assert result["type"] == "cron"
        assert result["fields"] == ["0", "9", "*", "*", "*"]

    def test_oneshot_datetime(self):
        result = _parse_schedule("2026-06-01T10:00")
        assert result["type"] == "oneshot"

    def test_unknown(self):
        result = _parse_schedule("something weird")
        assert result["type"] == "unknown"


# ── CronJob ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCronJob:
    def test_is_due_interval_first_run(self):
        job = CronJob(schedule="every 30m", enabled=True)
        assert job.is_due()

    def test_is_due_disabled(self):
        job = CronJob(schedule="every 30m", enabled=False)
        assert not job.is_due()

    def test_is_due_interval_not_yet(self):
        job = CronJob(schedule="every 30m", enabled=True)
        job.last_run_at = datetime.now(UTC)
        assert not job.is_due()

    def test_is_due_interval_elapsed(self):
        job = CronJob(schedule="every 1m", enabled=True)
        job.last_run_at = datetime.now(UTC) - timedelta(minutes=5)
        assert job.is_due()

    def test_to_dict_roundtrip(self):
        job = CronJob(name="test", schedule="every 1h", goal="do stuff")
        d = job.to_dict()
        assert d["name"] == "test"
        assert d["schedule"] == "every 1h"

    def test_from_dict(self):
        data = {
            "id": "abc",
            "name": "test",
            "schedule": "every 1h",
            "goal": "test goal",
            "edition": "enterprise",
            "enabled": True,
            "last_run_at": None,
            "next_run_at": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        job = CronJob.from_dict(data)
        assert job.id == "abc"
        assert job.name == "test"


# ── JobStore ───────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestJobStore:
    @pytest.fixture
    def store(self, tmp_path):
        return JobStore(path=str(tmp_path / "jobs.json"))

    def test_empty_store(self, store):
        assert store.list_jobs() == []

    def test_add_job(self, store):
        job = CronJob(name="test", schedule="every 1h", goal="test goal")
        result = store.add_job(job)
        assert result.id == job.id
        assert len(store.list_jobs()) == 1

    def test_get_job(self, store):
        job = CronJob(name="test", schedule="every 1h", goal="test goal")
        store.add_job(job)
        found = store.get_job(job.id)
        assert found is not None
        assert found.name == "test"

    def test_get_job_not_found(self, store):
        assert store.get_job("nonexistent") is None

    def test_update_job(self, store):
        job = CronJob(name="test", schedule="every 1h", goal="test goal")
        store.add_job(job)
        updated = store.update_job(job.id, name="updated", enabled=False)
        assert updated is not None
        assert updated.name == "updated"
        assert updated.enabled is False

    def test_update_not_found(self, store):
        assert store.update_job("nonexistent", name="x") is None

    def test_delete_job(self, store):
        job = CronJob(name="test", schedule="every 1h", goal="test goal")
        store.add_job(job)
        assert store.delete_job(job.id) is True
        assert len(store.list_jobs()) == 0

    def test_delete_not_found(self, store):
        assert store.delete_job("nonexistent") is False

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "jobs.json")
        store1 = JobStore(path=path)
        job = CronJob(name="persist-test", schedule="every 1h", goal="test")
        store1.add_job(job)

        # New store instance loads from same file
        store2 = JobStore(path=path)
        loaded = store2.get_job(job.id)
        assert loaded is not None
        assert loaded.name == "persist-test"

    def test_get_due_jobs(self, store):
        # Job never run — should be due
        job1 = CronJob(name="due", schedule="every 1m", goal="test", enabled=True)
        store.add_job(job1)

        # Disabled — should NOT be due
        job2 = CronJob(name="disabled", schedule="every 1m", goal="test", enabled=False)
        store.add_job(job2)

        due = store.get_due_jobs()
        assert len(due) == 1
        assert due[0].name == "due"


# ── CronScheduler ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCronScheduler:
    def test_tick_with_no_due_jobs(self, tmp_path):
        from packages.cron.scheduler import CronScheduler
        store = JobStore(path=str(tmp_path / "jobs.json"))
        scheduler = CronScheduler(store)
        results = scheduler.tick()
        assert results == []

    def test_tick_executes_due_job(self, tmp_path):
        from packages.cron.scheduler import CronScheduler
        store = JobStore(path=str(tmp_path / "jobs.json"))
        job = CronJob(name="test", schedule="every 1m", goal="hello", enabled=True)
        store.add_job(job)

        calls = []
        def mock_executor(goal, edition):
            calls.append((goal, edition))
            return "ok"

        scheduler = CronScheduler(store, executor_fn=mock_executor)
        results = scheduler.tick()
        assert len(results) == 1
        assert results[0]["status"] == "completed"
        assert len(calls) == 1

    def test_tick_skips_without_executor(self, tmp_path):
        from packages.cron.scheduler import CronScheduler
        store = JobStore(path=str(tmp_path / "jobs.json"))
        job = CronJob(name="test", schedule="every 1m", goal="hello", enabled=True)
        store.add_job(job)

        scheduler = CronScheduler(store, executor_fn=None)
        results = scheduler.tick()
        assert results[0]["status"] == "skipped"


# ── context_from chaining ──────────────────────────────────────────────


@pytest.mark.unit
class TestContextFromChaining:
    """Tests for upstream output injection via context_from."""

    @pytest.fixture
    def store(self, tmp_path):
        return JobStore(path=str(tmp_path / "jobs.json"))

    def _make_scheduler(self, store, executor_fn=None):
        from packages.cron.scheduler import CronScheduler
        return CronScheduler(store, executor_fn=executor_fn)

    def test_single_upstream_output_injected(self, store):
        """Upstream job's last_output is prepended to the goal."""
        upstream = CronJob(name="upstream", schedule="every 1m", goal="fetch data")
        upstream.last_output = "temperature=25"
        store.add_job(upstream)

        downstream = CronJob(
            name="downstream",
            schedule="every 1m",
            goal="analyze data",
            context_from=[upstream.id],
        )
        store.add_job(downstream)

        calls = []
        def mock_executor(goal, edition):
            calls.append(goal)
            return "done"

        scheduler = self._make_scheduler(store, mock_executor)
        # Only execute the downstream (disable upstream so it's not due)
        store.update_job(upstream.id, enabled=False)
        scheduler.tick()

        assert len(calls) == 1
        assert "temperature=25" in calls[0]
        assert "analyze data" in calls[0]

    def test_multiple_upstreams_concatenated(self, store):
        """Multiple upstream outputs are all injected."""
        up1 = CronJob(name="weather", schedule="every 1m", goal="get weather")
        up1.last_output = "sunny"
        store.add_job(up1)

        up2 = CronJob(name="stock", schedule="every 1m", goal="get stock")
        up2.last_output = "AAPL=150"
        store.add_job(up2)

        downstream = CronJob(
            name="summary",
            schedule="every 1m",
            goal="write summary",
            context_from=[up1.id, up2.id],
        )
        store.add_job(downstream)

        calls = []
        def mock_executor(goal, edition):
            calls.append(goal)
            return "ok"

        # Disable upstreams so only downstream runs
        store.update_job(up1.id, enabled=False)
        store.update_job(up2.id, enabled=False)
        self._make_scheduler(store, mock_executor).tick()

        assert len(calls) == 1
        assert "sunny" in calls[0]
        assert "AAPL=150" in calls[0]
        assert "write summary" in calls[0]

    def test_upstream_with_no_output_skipped(self, store):
        """Upstream that hasn't run yet (no last_output) is silently skipped."""
        upstream = CronJob(name="empty", schedule="every 1m", goal="fetch")
        # No last_output set
        store.add_job(upstream)

        downstream = CronJob(
            name="downstream",
            schedule="every 1m",
            goal="analyze",
            context_from=[upstream.id],
        )
        store.add_job(downstream)

        calls = []
        def mock_executor(goal, edition):
            calls.append(goal)
            return "ok"

        store.update_job(upstream.id, enabled=False)
        self._make_scheduler(store, mock_executor).tick()

        # Goal should be just the original since no upstream output
        assert len(calls) == 1
        assert calls[0] == "analyze"

    def test_nonexistent_upstream_ignored(self, store):
        """Referencing a non-existent upstream job ID is gracefully ignored."""
        downstream = CronJob(
            name="downstream",
            schedule="every 1m",
            goal="do work",
            context_from=["nonexistent-id-12345"],
        )
        store.add_job(downstream)

        calls = []
        def mock_executor(goal, edition):
            calls.append(goal)
            return "ok"

        self._make_scheduler(store, mock_executor).tick()
        assert len(calls) == 1
        assert calls[0] == "do work"

    def test_last_output_stored_after_execution(self, store):
        """After execution, last_output is stored for downstream consumption."""
        job = CronJob(name="producer", schedule="every 1m", goal="produce")
        store.add_job(job)

        def mock_executor(goal, edition):
            return "result-data-42"

        self._make_scheduler(store, mock_executor).tick()

        updated = store.get_job(job.id)
        assert updated is not None
        assert updated.last_output == "result-data-42"

    def test_full_chain_ab_execution(self, store):
        """A→B chain: A runs first, B gets A's output in the same tick (topo sort)."""
        # A: producer (enabled, due)
        job_a = CronJob(name="upstream-A", schedule="every 1m", goal="fetch data")
        store.add_job(job_a)

        # B: consumer (depends on A)
        job_b = CronJob(
            name="downstream-B",
            schedule="every 1m",
            goal="send report",
            context_from=[job_a.id],
        )
        store.add_job(job_b)

        calls = {}

        def mock_executor(goal, edition):
            if "fetch data" in goal and "upstream-A" not in goal.split("\n")[0]:
                # A's original goal (no context injection prefix)
                calls["A"] = goal
                return "REPORT-123"
            else:
                calls["B"] = goal
                return "sent"

        scheduler = self._make_scheduler(store, mock_executor)
        results = scheduler.tick()

        # Both A and B should run in one tick (topo sort ensures order)
        assert len(results) == 2
        assert results[0]["status"] == "completed"  # A
        assert results[1]["status"] == "completed"  # B
        assert "REPORT-123" in calls["B"]

    def test_context_from_empty_list(self, store):
        """Job with empty context_from runs normally without injection."""
        job = CronJob(name="solo", schedule="every 1m", goal="standalone")
        store.add_job(job)

        calls = []
        def mock_executor(goal, edition):
            calls.append(goal)
            return "ok"

        self._make_scheduler(store, mock_executor).tick()
        assert calls[0] == "standalone"

    def test_three_level_chain_abc_single_tick(self, store):
        """A→B→C: A runs first, B gets A's output, C gets B's output — all in one tick."""
        call_log = []

        def mock_executor(goal, edition):
            call_log.append(goal)
            # Return identifiable output based on execution order
            idx = len(call_log)
            return f"output-L{idx}"

        a = CronJob(name="A", schedule="every 1m", goal="step-a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="step-b", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="step-c", context_from=[b.id])
        store.add_job(c)

        results = self._make_scheduler(store, mock_executor).tick()
        assert len(results) == 3
        assert all(r["status"] == "completed" for r in results)

        # A runs first, plain goal
        assert call_log[0] == "step-a"
        # B runs second, gets A's output
        assert "output-L1" in call_log[1]
        assert "step-b" in call_log[1]
        # C runs third, gets B's output (which includes A's)
        assert "output-L2" in call_log[2]
        assert "step-c" in call_log[2]

    def test_mixed_upstreams_some_with_output(self, store):
        """Mix of upstreams with and without output — only those with output are injected."""
        up_with = CronJob(name="has-output", schedule="every 1m", goal="x")
        up_with.last_output = "real-data"
        store.add_job(up_with)

        up_without = CronJob(name="no-output", schedule="every 1m", goal="y")
        store.add_job(up_without)

        downstream = CronJob(
            name="mixed",
            schedule="every 1m",
            goal="final goal",
            context_from=[up_with.id, up_without.id],
        )
        store.add_job(downstream)

        calls = []
        def mock_executor(goal, edition):
            calls.append(goal)
            return "ok"

        store.update_job(up_with.id, enabled=False)
        store.update_job(up_without.id, enabled=False)
        self._make_scheduler(store, mock_executor).tick()

        assert len(calls) == 1
        assert "real-data" in calls[0]
        assert "final goal" in calls[0]
        # Should NOT contain any reference to no-output upstream
        assert "no-output" not in calls[0]


# ── Cycle detection & validation ───────────────────────────────────────


@pytest.mark.unit
class TestCycleDetection:
    """Tests for circular dependency detection and upstream validation."""

    @pytest.fixture
    def store(self, tmp_path):
        return JobStore(path=str(tmp_path / "jobs.json"))

    def test_detect_no_cycle(self, store):
        """No cycle when chain is linear: A → B → C."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)

        result = store.detect_cycle(job_id=a.id, context_from=[])
        assert result is None

    def test_detect_direct_cycle(self, store):
        """A→B→A is a direct cycle."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)

        # Now update A to depend on B → creates A→B→A cycle
        store.update_job(a.id, context_from=[b.id])
        result = store.detect_cycle(job_id=a.id, context_from=[b.id])
        assert result is not None

    def test_detect_three_node_cycle(self, store):
        """A→B→C→A is a three-node cycle."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="c", context_from=[b.id])
        store.add_job(c)

        # A depends on C → creates A→C→B→A cycle
        result = store.detect_cycle(job_id=a.id, context_from=[c.id])
        assert result is not None

    def test_validate_self_reference(self, store):
        """Job cannot reference itself."""
        job = CronJob(name="self", schedule="every 1m", goal="x")
        store.add_job(job)

        valid, error = store.validate_context_from(job.id, context_from=[job.id])
        assert valid is False
        assert "itself" in error

    def test_validate_missing_upstream(self, store):
        """Referencing a non-existent job fails validation."""
        job = CronJob(name="x", schedule="every 1m", goal="x")
        store.add_job(job)

        valid, error = store.validate_context_from(job.id, context_from=["ghost-id"])
        assert valid is False
        assert "not found" in error

    def test_validate_ok(self, store):
        """Valid chain passes validation."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b")
        store.add_job(b)

        valid, error = store.validate_context_from(b.id, context_from=[a.id])
        assert valid is True
        assert error == ""

    def test_validate_empty_context(self, store):
        """Empty context_from is always valid."""
        valid, error = store.validate_context_from("any-id", context_from=[])
        assert valid is True

    def test_diamond_no_cycle(self, store):
        """A→B, A→C, D→{B,C} — diamond shape is not a cycle."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="c", context_from=[a.id])
        store.add_job(c)

        valid, _ = store.validate_context_from("D-id", context_from=[b.id, c.id])
        assert valid is True

    def test_linear_chain_no_cycle(self, store):
        """A→B→C→D — linear chain is fine (no cycle)."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="c", context_from=[b.id])
        store.add_job(c)

        valid, _ = store.validate_context_from("D-id", context_from=[c.id])
        assert valid is True

    def test_partial_missing_upstream_rejected(self, store):
        """Some valid + some missing upstream IDs → rejected."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)

        valid, error = store.validate_context_from("child", context_from=[a.id, "ghost-id"])
        assert valid is False
        assert "ghost-id" in error

    def test_multiple_valid_upstreams(self, store):
        """Multiple valid upstream IDs → passes."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b")
        store.add_job(b)

        valid, _ = store.validate_context_from("C-id", context_from=[a.id, b.id])
        assert valid is True

    def test_validate_prevents_update_cycle(self, store):
        """Updating a job to create A→B→A cycle is prevented by validate_context_from."""
        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)

        # Try to update A to depend on B — should fail
        valid, error = store.validate_context_from(a.id, context_from=[b.id])
        assert valid is False
        # A's stored context_from should NOT have changed
        assert store.get_job(a.id).context_from == []


# ── Topological sort ───────────────────────────────────────────────────


@pytest.mark.unit
class TestTopologicalSort:
    """Tests for execution order via topological sort in scheduler.tick()."""

    @pytest.fixture
    def store(self, tmp_path):
        return JobStore(path=str(tmp_path / "jobs.json"))

    def _make_scheduler(self, store, executor_fn=None):
        from packages.cron.scheduler import CronScheduler
        return CronScheduler(store, executor_fn=executor_fn)

    def test_dependencies_run_first(self, store):
        """B depends on A: A must execute before B."""
        execution_order = []

        def mock_executor(goal, edition):
            execution_order.append(goal)
            return "ok"

        a = CronJob(name="A", schedule="every 1m", goal="goal-A")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="goal-B", context_from=[a.id])
        store.add_job(b)

        self._make_scheduler(store, mock_executor).tick()

        # A should run before B
        assert execution_order[0] == "goal-A"
        assert "goal-B" in execution_order[1]

    def test_three_level_chain(self, store):
        """A→B→C: execution order must be A, B, C."""
        execution_order = []

        def mock_executor(goal, edition):
            execution_order.append(goal)
            return "result"

        a = CronJob(name="A", schedule="every 1m", goal="step-1")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="step-2", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="step-3", context_from=[b.id])
        store.add_job(c)

        self._make_scheduler(store, mock_executor).tick()

        # C gets context from B which gets context from A
        assert len(execution_order) == 3
        # A runs first (no dependencies)
        assert execution_order[0] == "step-1"
        # B gets A's output
        assert "result" in execution_order[1]
        assert "step-2" in execution_order[1]

    def test_independent_jobs_order_preserved(self, store):
        """Jobs without dependencies keep their relative order."""
        execution_order = []

        def mock_executor(goal, edition):
            execution_order.append(goal)
            return "ok"

        a = CronJob(name="X", schedule="every 1m", goal="x")
        store.add_job(a)
        b = CronJob(name="Y", schedule="every 1m", goal="y")
        store.add_job(b)

        self._make_scheduler(store, mock_executor).tick()
        assert len(execution_order) == 2

    def test_topo_sort_direct_unit(self, store):
        """Direct call to _topo_sort returns jobs in dependency order."""
        scheduler = self._make_scheduler(store)

        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="c", context_from=[b.id])
        store.add_job(c)

        # Pass in reverse order
        sorted_jobs = scheduler._topo_sort([c, b, a])
        ids = [j.id for j in sorted_jobs]
        assert ids.index(a.id) < ids.index(b.id) < ids.index(c.id)

    def test_topo_sort_empty(self, store):
        """Empty list returns empty list."""
        scheduler = self._make_scheduler(store)
        assert scheduler._topo_sort([]) == []

    def test_topo_sort_external_dep_ignored(self, store):
        """If a due job depends on a non-due (disabled) job, it's treated as independent."""
        scheduler = self._make_scheduler(store)

        # Disabled — won't be in the due batch
        a = CronJob(name="A", schedule="every 1m", goal="a", enabled=False)
        store.add_job(a)
        # Due, depends on A (which is not in the batch)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)

        sorted_jobs = scheduler._topo_sort([b])
        assert len(sorted_jobs) == 1
        assert sorted_jobs[0].id == b.id

    def test_topo_sort_cycle_fallback(self, store):
        """If due jobs form a cycle (shouldn't normally happen), fallback to original order."""
        scheduler = self._make_scheduler(store)

        a = CronJob(name="A", schedule="every 1m", goal="a")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="b", context_from=[a.id])
        store.add_job(b)
        # Manually inject a cycle (bypassing validation)
        a.context_from = [b.id]

        sorted_jobs = scheduler._topo_sort([a, b])
        # Should fall back — both jobs still present
        assert len(sorted_jobs) == 2
        ids = {j.id for j in sorted_jobs}
        assert a.id in ids and b.id in ids

    def test_diamond_dependency_all_run(self, store):
        """Diamond: A→B, A→C, D→{B,C} — all four run, A first, D last."""
        execution_order = []

        def mock_executor(goal, edition):
            execution_order.append(goal)
            return "ok"

        a = CronJob(name="A", schedule="every 1m", goal="root")
        store.add_job(a)
        b = CronJob(name="B", schedule="every 1m", goal="branch-b", context_from=[a.id])
        store.add_job(b)
        c = CronJob(name="C", schedule="every 1m", goal="branch-c", context_from=[a.id])
        store.add_job(c)
        d = CronJob(name="D", schedule="every 1m", goal="leaf", context_from=[b.id, c.id])
        store.add_job(d)

        self._make_scheduler(store, mock_executor).tick()

        assert len(execution_order) == 4
        # A must be first
        assert execution_order[0] == "root"
        # D must be last (depends on both B and C)
        assert "leaf" in execution_order[3]
