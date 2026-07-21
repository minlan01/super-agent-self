"""Job Store — JSON file storage for cron jobs with atomic writes."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_schedule(schedule: str) -> dict[str, Any]:
    """Parse a schedule string into a structured form.

    Supports:
    - "every Ns/m/h/d" — interval-based
    - Cron expressions: "M H DoM Mon DoW" (5-field)
    - ISO datetime: "2026-06-01T10:00" — one-shot
    """
    schedule = schedule.strip()

    # Interval: "every 30m", "every 1h", "every 5s", "every 2d"
    if schedule.startswith("every "):
        parts = schedule.split()
        if len(parts) == 2:
            val = parts[1]
            num = int("".join(c for c in val if c.isdigit()) or "0")
            unit = val[-1] if val else ""
            return {"type": "interval", "value": num, "unit": unit, "raw": schedule}

    # One-shot ISO datetime
    try:
        dt = datetime.fromisoformat(schedule)
        return {"type": "oneshot", "datetime": dt.isoformat(), "raw": schedule}
    except (ValueError, TypeError):
        pass

    # Cron expression (5 fields)
    fields = schedule.split()
    if len(fields) == 5:
        return {"type": "cron", "fields": fields, "raw": schedule}

    return {"type": "unknown", "raw": schedule}


def _matches_interval(parsed: dict, now: datetime, last_run: datetime | None) -> bool:
    """Check if an interval schedule is due."""
    if last_run is None:
        return True
    unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = parsed.get("value", 0) * unit_map.get(parsed.get("unit", "s"), 60)
    elapsed = (now - last_run).total_seconds()
    return elapsed >= seconds


def _matches_cron(parsed: dict, now: datetime) -> bool:
    """Cron matcher — checks all 5 fields (minute/hour/day-of-month/month/day-of-week)."""
    fields = parsed.get("fields", ["*"] * 5)
    try:
        if fields[0] != "*" and now.minute != int(fields[0]):
            return False
        if fields[1] != "*" and now.hour != int(fields[1]):
            return False
        if fields[2] != "*" and now.day != int(fields[2]):
            return False
        if fields[3] != "*" and now.month != int(fields[3]):
            return False
        if fields[4] != "*" and now.weekday() != int(fields[4]) % 7:
            return False
        return True
    except (ValueError, IndexError):
        return False


def _matches_oneshot(parsed: dict, now: datetime, executed: set[str] | None = None) -> bool:
    """Check if a one-shot schedule has been reached and not yet executed."""
    job_id = parsed.get("_job_id")
    if job_id and executed and job_id in executed:
        return False
    try:
        target = datetime.fromisoformat(parsed["datetime"])
        # Match if within the same minute
        return now >= target and (now - target).total_seconds() < 60
    except (KeyError, ValueError):
        return False


@dataclass
class CronJob:
    id: str = field(default_factory=_uuid)
    name: str = ""
    schedule: str = "every 60m"
    goal: str = ""
    edition: str = "enterprise"
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    context_from: list[str] = field(default_factory=list)  # job IDs whose output to inject
    last_output: str | None = None  # last execution output

    def __post_init__(self):
        self._parsed = _parse_schedule(self.schedule)

    def is_due(self, now: datetime | None = None) -> bool:
        """Check if this job is due to run."""
        if not self.enabled:
            return False
        now = now or _now()
        parsed = getattr(self, "_parsed", _parse_schedule(self.schedule))
        ptype = parsed.get("type", "unknown")

        if ptype == "interval":
            return _matches_interval(parsed, now, self.last_run_at)
        elif ptype == "cron":
            return _matches_cron(parsed, now)
        elif ptype == "oneshot":
            parsed["_job_id"] = self.id
            return _matches_oneshot(parsed, now, getattr(self, '_executed_oneshots', None))
        return False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert datetimes to ISO format
        for key in ("last_run_at", "next_run_at", "created_at"):
            if d[key] is not None:
                d[key] = d[key].isoformat() if isinstance(d[key], datetime) else d[key]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJob:
        """Create a CronJob from a dict (e.g., loaded from JSON)."""
        for key in ("last_run_at", "next_run_at", "created_at"):
            if data.get(key) and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class JobStore:
    """JSON file storage for cron jobs with atomic writes."""

    def __init__(self, path: str = "data/cron/jobs.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, CronJob] = {}
        self._executed_oneshots: set[str] = set()
        self._executed_path = Path(str(self.path).replace("jobs.json", "executed_oneshots.json"))
        self._load_executed_oneshots()
        self._load()

    def _load_executed_oneshots(self) -> None:
        """Load executed one-shot job IDs from JSON file."""
        if not self._executed_path.exists():
            return
        try:
            data = json.loads(self._executed_path.read_text(encoding="utf-8"))
            self._executed_oneshots = set(data if isinstance(data, list) else data.get("ids", []))
            logger.info("Loaded %d executed oneshot IDs from %s", len(self._executed_oneshots), self._executed_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load executed oneshots: %s", exc)

    def _save_executed_oneshots(self) -> None:
        """Persist executed one-shot job IDs to JSON file."""
        try:
            self._executed_path.write_text(
                json.dumps(list(self._executed_oneshots), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save executed oneshots: %s", exc)

    def mark_oneshot_executed(self, job_id: str) -> None:
        """Mark a one-shot job as executed and persist the record."""
        self._executed_oneshots.add(job_id)
        self._save_executed_oneshots()

    def _load(self) -> None:
        """Load jobs from JSON file."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for job_data in data:
                job = CronJob.from_dict(job_data)
                self._jobs[job.id] = job
            logger.info("Loaded %d cron jobs from %s", len(self._jobs), self.path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load cron jobs: %s", exc)

    def _save(self) -> None:
        """Atomic write of all jobs to JSON file."""
        tmp_path = self.path.with_suffix(".tmp")
        try:
            data = [job.to_dict() for job in self._jobs.values()]
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self.path)
        except OSError as exc:
            logger.error("Failed to save cron jobs: %s", exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def list_jobs(self) -> list[CronJob]:
        """List all jobs."""
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> CronJob | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def add_job(self, job: CronJob) -> CronJob:
        """Add a new job."""
        self._jobs[job.id] = job
        self._save()
        return job

    def update_job(self, job_id: str, **kwargs) -> CronJob | None:
        """Update a job's fields."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        if "schedule" in kwargs:
            job._parsed = _parse_schedule(job.schedule)
        self._save()
        return job

    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False

    def get_due_jobs(self, now: datetime | None = None) -> list[CronJob]:
        """Get all jobs that are due to run."""
        now = now or _now()
        due = []
        for job in self._jobs.values():
            job._executed_oneshots = self._executed_oneshots
            if job.is_due(now):
                due.append(job)
        return due

    def detect_cycle(
        self, job_id: str, context_from: list[str], visited: set[str] | None = None
    ) -> list[str] | None:
        """Detect if adding context_from to job_id would create a cycle.

        Returns the cycle path as a list of job IDs, or None if no cycle.
        """
        if visited is None:
            visited = set()

        if job_id in visited:
            return list(visited) + [job_id]

        visited.add(job_id)

        for upstream_id in context_from:
            # Check if upstream_id leads back to job_id
            upstream = self._jobs.get(upstream_id)
            if upstream is None:
                continue
            cycle = self.detect_cycle(
                job_id=upstream_id,
                context_from=upstream.context_from,
                visited=set(visited),
            )
            if cycle is not None:
                return cycle

        return None

    def validate_context_from(
        self, job_id: str, context_from: list[str]
    ) -> tuple[bool, str]:
        """Validate context_from references: existence, no self-ref, no cycles.

        Returns (is_valid, error_message).
        """
        if not context_from:
            return True, ""

        # Self-reference
        if job_id in context_from:
            return False, "Job cannot reference itself in context_from"

        # Existence check
        missing = [uid for uid in context_from if uid not in self._jobs]
        if missing:
            return False, f"Upstream job(s) not found: {', '.join(missing)}"

        # Cycle detection
        cycle = self.detect_cycle(job_id, context_from)
        if cycle is not None:
            return False, f"Circular dependency detected: {' → '.join(cycle)}"

        return True, ""
