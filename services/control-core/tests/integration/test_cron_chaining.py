"""Integration test — Cron job chaining: upstream output flows into downstream goal."""

import pytest

from packages.cron.jobs import CronJob, JobStore
from packages.cron.scheduler import CronScheduler


@pytest.fixture
def store(tmp_path):
    return JobStore(path=str(tmp_path / "cron_jobs.json"))


class TestCronChainingIntegration:
    """Full integration test for context_from chaining via scheduler."""

    def test_two_job_chain_output_flows(self, store):
        """A→B chain: A produces output, B receives it in goal."""
        job_a = CronJob(name="fetcher", schedule="every 1m", goal="fetch market data")
        store.add_job(job_a)

        job_b = CronJob(
            name="analyzer",
            schedule="every 1m",
            goal="analyze and summarize",
            context_from=[job_a.id],
        )
        store.add_job(job_b)

        execution_log = {}

        def executor(goal, edition):
            if "fetch market data" in goal:
                execution_log["A_goal"] = goal
                return "AAPL:180, GOOG:140, MSFT:420"
            else:
                execution_log["B_goal"] = goal
                return "Market summary: tech stocks up 3%"

        scheduler = CronScheduler(store, executor_fn=executor)
        results = scheduler.tick()

        # Both jobs executed in one tick (topological sort)
        assert len(results) == 2
        assert results[0]["status"] == "completed"
        assert results[1]["status"] == "completed"

        # B's goal contains A's output
        assert "AAPL:180" in execution_log["B_goal"]
        assert "analyze and summarize" in execution_log["B_goal"]

    def test_three_job_chain_a_to_b_to_c(self, store):
        """A→B→C: three-level chain with output propagation."""
        job_a = CronJob(name="collector", schedule="every 1m", goal="collect data")
        store.add_job(job_a)

        job_b = CronJob(
            name="processor",
            schedule="every 1m",
            goal="process data",
            context_from=[job_a.id],
        )
        store.add_job(job_b)

        job_c = CronJob(
            name="reporter",
            schedule="every 1m",
            goal="generate report",
            context_from=[job_b.id],
        )
        store.add_job(job_c)

        execution_log = {}

        def executor(goal, edition):
            if "collect data" in goal and "collector" not in goal:
                execution_log["A"] = goal
                return "raw: 1,2,3"
            elif "process data" in goal or "raw:" in goal:
                execution_log["B"] = goal
                return "processed: sum=6, avg=2"
            else:
                execution_log["C"] = goal
                return "Report: data processed successfully"

        scheduler = CronScheduler(store, executor_fn=executor)
        results = scheduler.tick()

        assert len(results) == 3
        assert all(r["status"] == "completed" for r in results)

        # B got A's output
        assert "raw: 1,2,3" in execution_log["B"]
        # C got B's output
        assert "processed: sum=6" in execution_log["C"]

    def test_chain_with_missing_upstream(self, store):
        """Job referencing nonexistent upstream still runs (graceful degradation)."""
        job = CronJob(
            name="solo",
            schedule="every 1m",
            goal="work independently",
            context_from=["nonexistent-id"],
        )
        store.add_job(job)

        calls = []
        def executor(goal, edition):
            calls.append(goal)
            return "ok"

        CronScheduler(store, executor_fn=executor).tick()
        assert calls[0] == "work independently"

    def test_disabled_upstream_output_still_injected(self, store):
        """Disabled upstream's last_output is still available for injection."""
        job_a = CronJob(name="source", schedule="every 1m", goal="produce")
        job_a.last_output = "cached-result-42"
        job_a.enabled = False  # disabled but has output
        store.add_job(job_a)

        job_b = CronJob(
            name="consumer",
            schedule="every 1m",
            goal="consume",
            context_from=[job_a.id],
        )
        store.add_job(job_b)

        calls = []
        def executor(goal, edition):
            calls.append(goal)
            return "done"

        CronScheduler(store, executor_fn=executor).tick()
        assert "cached-result-42" in calls[0]

    def test_persisted_chain_across_scheduler_restarts(self, store):
        """Chain data persists: A runs in tick 1, B reads A's output in tick 2."""
        job_a = CronJob(name="A", schedule="every 1m", goal="produce")
        store.add_job(job_a)

        job_b = CronJob(
            name="B",
            schedule="every 1m",
            goal="consume",
            context_from=[job_a.id],
        )
        store.add_job(job_b)

        def executor_a(goal, edition):
            return "output-from-A"

        # Tick 1: both run, A produces output
        scheduler1 = CronScheduler(store, executor_fn=executor_a)
        results1 = scheduler1.tick()
        assert len(results1) == 2

        # Verify A's output is stored
        updated_a = store.get_job(job_a.id)
        assert updated_a.last_output == "output-from-A"

        # Tick 2: reset B's last_run so it's due again
        store.update_job(job_b.id, last_run_at=None)
        store.update_job(job_a.id, enabled=False)  # don't re-run A

        calls = []
        def executor_b(goal, edition):
            calls.append(goal)
            return "done"

        CronScheduler(store, executor_fn=executor_b).tick()
        assert "output-from-A" in calls[0]
