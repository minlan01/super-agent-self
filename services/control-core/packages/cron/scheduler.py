"""Cron Scheduler — background thread for scheduled task execution."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from packages.cron.jobs import JobStore

logger = logging.getLogger(__name__)


class CronScheduler:
    """Background thread that checks for due jobs every 60 seconds and executes them."""

    def __init__(
        self,
        job_store: JobStore,
        executor_fn: Callable[[str, str], Any] | None = None,
        tick_interval: int = 60,
    ):
        self.job_store = job_store
        self.executor_fn = executor_fn
        self.tick_interval = tick_interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._job_errors: dict[str, list[str]] = {}
        self._max_tracked_jobs = 100
        self._errors_lock = threading.Lock()

    def _cleanup_stale_errors(self) -> None:
        """Remove error records for jobs that no longer exist."""
        if not hasattr(self.job_store, 'list_jobs'):
            return
        jobs = self.job_store.list_jobs()
        known_ids = {j.id if hasattr(j, 'id') else str(j) for j in jobs}
        if not known_ids:
            return
        with self._errors_lock:
            stale = [jid for jid in self._job_errors if jid not in known_ids]
            for jid in stale:
                del self._job_errors[jid]
            if len(self._job_errors) > self._max_tracked_jobs:
                sorted_ids = sorted(self._job_errors, key=lambda k: len(self._job_errors[k]), reverse=True)
                for jid in sorted_ids[self._max_tracked_jobs:]:
                    del self._job_errors[jid]

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Scheduler already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="cron-scheduler")
        self._thread.start()
        logger.info("Cron scheduler started (interval: %ds)", self.tick_interval)

    def stop(self) -> None:
        """Stop the scheduler."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Cron scheduler stopped")

    def _run(self) -> None:
        """Main loop — tick at interval."""
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.warning("Cron job error: %s", e)
            self._stop_event.wait(self.tick_interval)

    def tick(self) -> list[dict[str, Any]]:
        """Check for due jobs and execute them. Returns list of execution results."""
        self._cleanup_stale_errors()
        now = datetime.now(UTC)
        due_jobs = self.job_store.get_due_jobs(now)

        # Topological sort: dependencies run before dependents
        due_jobs = self._topo_sort(due_jobs)

        results = []
        for job in due_jobs:
            logger.info("Executing cron job '%s' (%s)", job.name, job.id)
            result = self._execute_job(job)
            results.append(result)

            # Update last_run_at
            self.job_store.update_job(job.id, last_run_at=now)

            # Mark one-shot jobs as executed to prevent re-run
            parsed = getattr(job, "_parsed", None)
            if parsed and parsed.get("type") == "oneshot" and hasattr(self.job_store, "mark_oneshot_executed"):
                self.job_store.mark_oneshot_executed(job.id)

        return results

    def _topo_sort(self, jobs: list[Any]) -> list[Any]:
        """Sort jobs so that dependencies (context_from) run before dependents."""
        if not jobs:
            return jobs

        job_map = {job.id: job for job in jobs}
        job_ids = set(job_map.keys())

        # Build in-degree and adjacency for jobs in this batch only
        in_degree: dict[str, int] = {jid: 0 for jid in job_ids}
        # adj[a] = [b] means a must run before b
        adj: dict[str, list[str]] = {jid: [] for jid in job_ids}

        for job in jobs:
            for upstream_id in job.context_from:
                if upstream_id in job_ids:
                    adj[upstream_id].append(job.id)
                    in_degree[job.id] += 1

        # Kahn's algorithm
        queue = deque(jid for jid, deg in in_degree.items() if deg == 0)
        sorted_ids: list[str] = []

        while queue:
            jid = queue.popleft()
            sorted_ids.append(jid)
            for neighbor in adj[jid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If cycle among due jobs, fall back to original order
        if len(sorted_ids) != len(job_ids):
            return jobs

        return [job_map[jid] for jid in sorted_ids]

    def _execute_job(self, job: Any) -> dict[str, Any]:
        """Execute a single cron job."""
        if self.executor_fn is None:
            logger.warning("No executor function configured, skipping job '%s'", job.name)
            return {"job_id": job.id, "status": "skipped", "reason": "no executor"}

        # Build goal with context_from upstream outputs
        goal = job.goal
        if job.context_from:
            context_parts = []
            for upstream_id in job.context_from:
                upstream = self.job_store.get_job(upstream_id)
                if upstream and upstream.last_output:
                    context_parts.append(f"[Output from '{upstream.name}']:\n{upstream.last_output}")
            if context_parts:
                goal = "\n\n".join(context_parts) + "\n\n---\n\n" + goal

        try:
            result = self.executor_fn(goal, job.edition)
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(asyncio.run, result).result(timeout=300)
                else:
                    result = asyncio.run(result)
            logger.info("Cron job '%s' completed: %s", job.name, str(result)[:200])
            self.job_store.update_job(job.id, last_output=str(result))
            return {"job_id": job.id, "status": "completed", "result": str(result)}
        except Exception as exc:
            logger.exception("Cron job '%s' failed", job.name)
            with self._errors_lock:
                errors = self._job_errors.setdefault(job.id, [])
                errors.append(f"{datetime.now(UTC).isoformat()}: {type(exc).__name__}")
                if len(errors) > 50:
                    self._job_errors[job.id] = errors[-50:]
            return {"job_id": job.id, "status": "failed", "error": type(exc).__name__}
