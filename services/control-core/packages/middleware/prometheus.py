"""Prometheus-compatible metrics middleware — pure Python implementation.

Tracks HTTP request counts, durations, agent task counts, active WebSocket
connections, and active DB connections.  Exposes a singleton ``registry``
so the /metrics endpoint can render the collected data without external
dependencies (no ``prometheus_client`` required).
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# ── Metric primitives ────────────────────────────────────────────────────


class Counter:
    """Thread-safe Prometheus counter."""

    def __init__(self, name: str, help_text: str, label_names: list[str] | None = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._values: dict[tuple[str, ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None):
        key = self._label_key(labels)
        with self._lock:
            self._values[key] += value

    def get(self, labels: dict[str, str] | None = None) -> float:
        key = self._label_key(labels)
        with self._lock:
            return self._values[key]

    def all_samples(self) -> list[tuple[tuple[str, str], ...], float]:
        with self._lock:
            return list(self._values.items())

    def _label_key(self, labels: dict[str, str] | None) -> tuple[str, ...]:
        if labels is None:
            labels = {}
        return tuple(labels.get(k, "") for k in self.label_names)


class Histogram:
    """Thread-safe Prometheus histogram with configurable buckets."""

    # Default Prometheus buckets (seconds)
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, float("inf"))

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: list[str] | None = None,
        buckets: tuple[float, ...] | None = None,
    ):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        # {label_key: {bucket: cumulative_count}}
        self._counts: dict[tuple[str, ...], dict[float, int]] = {}
        # {label_key: sum_of_observations}
        self._sums: dict[tuple[str, ...], float] = {}
        # {label_key: total_count}
        self._totals: dict[tuple[str, ...], int] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, labels: dict[str, str] | None = None):
        key = self._label_key(labels)
        with self._lock:
            if key not in self._counts:
                self._counts[key] = {b: 0 for b in self.buckets}
                self._sums[key] = 0.0
                self._totals[key] = 0
            self._sums[key] += value
            self._totals[key] += 1
            for b in self.buckets:
                if value <= b:
                    self._counts[key][b] += 1

    def get_samples(self, labels: dict[str, str] | None = None) -> list[tuple[str, dict[str, str], float]]:
        """Return all samples for a label set as [(metric_name, labels, value), ...]."""
        key = self._label_key(labels)
        with self._lock:
            counts = self._counts.get(key, {})
            total_sum = self._sums.get(key, 0.0)
            total_count = self._totals.get(key, 0)
            result: list[tuple[str, dict[str, str], float]] = []
            for b in self.buckets:
                le_label = {"le": self._format_le(b)}
                if labels:
                    le_label.update(labels)
                result.append((f"{self.name}_bucket", le_label, counts.get(b, 0)))
            # _sum and _count
            sum_label = labels or {}
            result.append((f"{self.name}_sum", sum_label, total_sum))
            result.append((f"{self.name}_count", sum_label, total_count))
            return result

    def all_label_keys(self) -> list[tuple[str, ...]]:
        with self._lock:
            return list(self._counts.keys())

    def _label_key(self, labels: dict[str, str] | None) -> tuple[str, ...]:
        if labels is None:
            labels = {}
        return tuple(labels.get(k, "") for k in self.label_names)

    @staticmethod
    def _format_le(value: float) -> str:
        if value == float("inf"):
            return "+Inf"
        return str(value)


class Gauge:
    """Thread-safe Prometheus gauge."""

    def __init__(self, name: str, help_text: str, label_names: list[str] | None = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._values: dict[tuple[str, ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, labels: dict[str, str] | None = None):
        key = self._label_key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None):
        key = self._label_key(labels)
        with self._lock:
            self._values[key] += value

    def dec(self, value: float = 1.0, labels: dict[str, str] | None = None):
        key = self._label_key(labels)
        with self._lock:
            self._values[key] -= value

    def get(self, labels: dict[str, str] | None = None) -> float:
        key = self._label_key(labels)
        with self._lock:
            return self._values[key]

    def all_samples(self) -> list[tuple[tuple[str, str], ...], float]:
        with self._lock:
            return list(self._values.items())

    def _label_key(self, labels: dict[str, str] | None) -> tuple[str, ...]:
        if labels is None:
            labels = {}
        return tuple(labels.get(k, "") for k in self.label_names)


# ── Metrics Registry (singleton) ─────────────────────────────────────────


class MetricsRegistry:
    """Central registry holding all Prometheus metric instances."""

    def __init__(self):
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            label_names=["method", "path", "status"],
        )
        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            label_names=["method", "path"],
        )
        self.agent_tasks_total = Counter(
            "agent_tasks_total",
            "Total agent tasks executed",
            label_names=["status"],
        )
        self.agent_active_websockets = Gauge(
            "agent_active_websockets",
            "Number of active WebSocket connections",
        )
        self.agent_db_connections_active = Gauge(
            "agent_db_connections_active",
            "Number of active database connections",
        )
        self.llm_cost_total = Counter(
            "llm_cost_total",
            "Total estimated LLM cost in USD",
            label_names=["provider", "model"],
        )
        self.skill_runs_total = Counter(
            "skill_runs_total",
            "Total skill execution runs",
            label_names=["skill_name", "status"],
        )
        self.task_execution_duration_seconds = Histogram(
            "task_execution_duration_seconds",
            "Task execution duration in seconds",
            label_names=["status"],
        )

    def all_metrics(self) -> list[Counter | Histogram | Gauge]:
        return [
            self.http_requests_total,
            self.http_request_duration_seconds,
            self.agent_tasks_total,
            self.agent_active_websockets,
            self.agent_db_connections_active,
            self.llm_cost_total,
            self.skill_runs_total,
            self.task_execution_duration_seconds,
        ]


# Module-level singleton
registry = MetricsRegistry()


# ── Middleware ────────────────────────────────────────────────────────────


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Collect Prometheus metrics for every HTTP request.

    Records ``http_requests_total`` and ``http_request_duration_seconds``
    for each request.  Paths that are exact matches of the ``/metrics``
    endpoint are excluded to avoid self-referential noise.

    Dynamic path segments (UUIDs, numeric IDs) are collapsed to
    ``{id}`` to prevent high-cardinality label explosion.
    """

    _UUID_RE = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
    )
    _NUM_ID_RE = re.compile(r"/(?=\d+)(?:\d+)(?=/|$)")

    SKIP_PREFIXES = ("/api/v1/metrics", "/health")

    def __init__(self, app: Any, skip_prefixes: list[str] | None = None):
        super().__init__(app)
        if skip_prefixes is not None:
            self.skip_prefixes = skip_prefixes
        else:
            self.skip_prefixes = list(self.SKIP_PREFIXES)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if any(path.startswith(prefix) for prefix in self.skip_prefixes):
            return await call_next(request)

        method = request.method
        start = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start
        status = str(response.status_code)

        normalized = self._normalize_path(path)
        registry.http_requests_total.inc(labels={"method": method, "path": normalized, "status": status})
        registry.http_request_duration_seconds.observe(duration, labels={"method": method, "path": normalized})

        return response

    @classmethod
    def _normalize_path(cls, path: str) -> str:
        path = cls._UUID_RE.sub("{id}", path)
        path = cls._NUM_ID_RE.sub("/{id}", path)
        return path
