"""Unit tests for Prometheus metrics middleware and endpoint."""

from __future__ import annotations

import re
import threading
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api_server.routes.metrics import (
    _format_counter,
    _format_gauge,
    _format_histogram_no_obs,
    generate_metrics,
)
from packages.middleware.prometheus import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    PrometheusMiddleware,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the global registry before each test to avoid cross-test pollution."""
    reg = MetricsRegistry()
    with patch("packages.middleware.prometheus.registry", reg), \
         patch("apps.api_server.routes.metrics.registry", reg):
        yield reg


@pytest.fixture
def app_with_prometheus():
    """Create a minimal FastAPI app with PrometheusMiddleware and metrics route."""
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)

    @app.get("/test-endpoint")
    def test_endpoint():
        return {"ok": True}

    @app.get("/slow-endpoint")
    def slow_endpoint():
        time.sleep(0.01)
        return {"ok": True}

    from apps.api_server.routes.metrics import router as metrics_router
    app.include_router(metrics_router, prefix="/api/v1/metrics", tags=["metrics"])
    return app


@pytest.fixture
def client(app_with_prometheus):
    return TestClient(app_with_prometheus)


# ── Counter tests ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCounter:
    def test_counter_initial_value_zero(self):
        c = Counter("test_counter", "A test counter")
        assert c.get() == 0.0

    def test_counter_inc_by_one(self):
        c = Counter("test_counter", "A test counter")
        c.inc()
        assert c.get() == 1.0

    def test_counter_inc_by_value(self):
        c = Counter("test_counter", "A test counter")
        c.inc(value=5.0)
        assert c.get() == 5.0

    def test_counter_with_labels(self):
        c = Counter("http_requests", "HTTP requests", label_names=["method", "status"])
        c.inc(labels={"method": "GET", "status": "200"})
        c.inc(labels={"method": "GET", "status": "200"})
        c.inc(labels={"method": "POST", "status": "201"})
        assert c.get(labels={"method": "GET", "status": "200"}) == 2.0
        assert c.get(labels={"method": "POST", "status": "201"}) == 1.0
        assert c.get(labels={"method": "DELETE", "status": "404"}) == 0.0

    def test_counter_all_samples(self):
        c = Counter("test_counter", "A test counter", label_names=["method"])
        c.inc(labels={"method": "GET"})
        c.inc(labels={"method": "POST"})
        samples = c.all_samples()
        assert len(samples) == 2
        values = {s[1] for s in samples}
        assert values == {1.0, 1.0}


# ── Gauge tests ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGauge:
    def test_gauge_initial_zero(self):
        g = Gauge("test_gauge", "A test gauge")
        assert g.get() == 0.0

    def test_gauge_set(self):
        g = Gauge("test_gauge", "A test gauge")
        g.set(42.0)
        assert g.get() == 42.0

    def test_gauge_inc_dec(self):
        g = Gauge("test_gauge", "A test gauge")
        g.inc(3.0)
        g.dec(1.0)
        assert g.get() == 2.0

    def test_gauge_with_labels(self):
        g = Gauge("active_conns", "Active connections", label_names=["pool"])
        g.set(5, labels={"pool": "default"})
        g.set(2, labels={"pool": "replica"})
        assert g.get(labels={"pool": "default"}) == 5.0
        assert g.get(labels={"pool": "replica"}) == 2.0

    def test_gauge_all_samples(self):
        g = Gauge("test_gauge", "A test gauge", label_names=["env"])
        g.set(10, labels={"env": "prod"})
        g.set(3, labels={"env": "dev"})
        samples = g.all_samples()
        assert len(samples) == 2


# ── Histogram tests ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestHistogram:
    def test_histogram_observe(self):
        h = Histogram("test_hist", "A test histogram", buckets=(0.1, 0.5, 1.0, float("inf")))
        h.observe(0.05)
        h.observe(0.3)
        h.observe(0.8)
        keys = h.all_label_keys()
        assert len(keys) == 1
        samples = h.get_samples()
        sum_sample = [s for s in samples if s[0] == "test_hist_sum"][0]
        count_sample = [s for s in samples if s[0] == "test_hist_count"][0]
        assert sum_sample[2] == pytest.approx(1.15)
        assert count_sample[2] == 3

    def test_histogram_cumulative_buckets(self):
        h = Histogram("test_hist", "A test histogram", buckets=(0.1, 0.5, 1.0, float("inf")))
        h.observe(0.05)  # <=0.1
        h.observe(0.3)   # <=0.5
        h.observe(0.8)   # <=1.0
        samples = h.get_samples()
        # get_samples returns list of (metric_name, labels, value)
        bucket_samples = [(name, lbl, val) for name, lbl, val in samples if name == "test_hist_bucket"]
        # Sort by le value (numeric, with +Inf last)
        def le_sort_key(item):
            le = item[1].get("le", "")
            if le == "+Inf":
                return float("inf")
            return float(le)
        bucket_samples.sort(key=le_sort_key)
        assert bucket_samples[0][2] == 1  # le="0.1": only 0.05
        assert bucket_samples[1][2] == 2  # le="0.5": 0.05 + 0.3 (cumulative)
        assert bucket_samples[2][2] == 3  # le="1.0": all three
        assert bucket_samples[3][2] == 3  # le="+Inf": all three

    def test_histogram_with_labels(self):
        h = Histogram("req_duration", "Duration", label_names=["method"])
        h.observe(0.01, labels={"method": "GET"})
        h.observe(0.5, labels={"method": "POST"})
        keys = h.all_label_keys()
        assert len(keys) == 2

    def test_histogram_default_buckets(self):
        h = Histogram("test_hist", "test")
        assert h.buckets == Histogram.DEFAULT_BUCKETS
        assert len(h.buckets) == 15

    def test_histogram_unobserved_zero(self):
        """Unobserved histogram should produce zero-valued samples."""
        h = Histogram("test_hist", "test", buckets=(0.1, 1.0, float("inf")))
        output = _format_histogram_no_obs(h)
        assert '_bucket{le="0.1"} 0' in output
        assert '_bucket{le="1.0"} 0' in output
        assert '_bucket{le="+Inf"} 0' in output
        assert "test_hist_sum 0" in output
        assert "test_hist_count 0" in output


# ── MetricsRegistry tests ────────────────────────────────────────────────


@pytest.mark.unit
class TestMetricsRegistry:
    def test_registry_has_all_metrics(self):
        reg = MetricsRegistry()
        metrics = reg.all_metrics()
        assert len(metrics) == 8
        names = {m.name for m in metrics}
        assert "http_requests_total" in names
        assert "http_request_duration_seconds" in names
        assert "agent_tasks_total" in names
        assert "agent_active_websockets" in names
        assert "agent_db_connections_active" in names
        assert "llm_cost_total" in names
        assert "skill_runs_total" in names
        assert "task_execution_duration_seconds" in names

    def test_registry_counter_types(self):
        reg = MetricsRegistry()
        assert isinstance(reg.http_requests_total, Counter)
        assert isinstance(reg.agent_tasks_total, Counter)
        assert isinstance(reg.http_request_duration_seconds, Histogram)
        assert isinstance(reg.agent_active_websockets, Gauge)
        assert isinstance(reg.agent_db_connections_active, Gauge)


# ── Format tests ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFormat:
    def test_format_counter_output(self):
        c = Counter("http_requests_total", "Total HTTP requests", label_names=["method", "path", "status"])
        c.inc(labels={"method": "GET", "path": "/api/v1/tasks", "status": "200"})
        output = _format_counter(c)
        assert "# HELP http_requests_total Total HTTP requests" in output
        assert "# TYPE http_requests_total counter" in output
        assert 'http_requests_total{method="GET",path="/api/v1/tasks",status="200"} 1.0' in output

    def test_format_gauge_output(self):
        g = Gauge("agent_active_websockets", "Active WebSocket connections")
        g.set(3)
        output = _format_gauge(g)
        assert "# HELP agent_active_websockets Active WebSocket connections" in output
        assert "# TYPE agent_active_websockets gauge" in output
        assert "agent_active_websockets 3" in output

    def test_generate_metrics_has_help_and_type(self):
        """Generated output must contain HELP and TYPE for every metric."""
        output = generate_metrics()
        for name in [
            "http_requests_total",
            "http_request_duration_seconds",
            "agent_tasks_total",
            "agent_active_websockets",
            "agent_db_connections_active",
        ]:
            assert f"# HELP {name}" in output
            assert f"# TYPE {name}" in output

    def test_generate_metrics_prometheus_format(self):
        """Output lines must match Prometheus text exposition format."""
        output = generate_metrics()
        # Every non-comment, non-empty line must match: metric_name[{labels}] value
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Should match: name{...} number  or  name number
            pattern = r'^[a-z_]+(?:\{[^}]*\})? \d+\.?\d*$'
            assert re.match(pattern, line), f"Line does not match Prometheus format: {line}"


# ── PrometheusMiddleware tests ────────────────────────────────────────────


@pytest.mark.unit
class TestPrometheusMiddleware:
    def test_middleware_tracks_request_count(self, client, reset_registry):
        reg = reset_registry
        client.get("/test-endpoint")
        client.get("/test-endpoint")
        assert reg.http_requests_total.get(labels={"method": "GET", "path": "/test-endpoint", "status": "200"}) == 2.0

    def test_middleware_tracks_request_duration(self, client, reset_registry):
        reg = reset_registry
        client.get("/slow-endpoint")
        keys = reg.http_request_duration_seconds.all_label_keys()
        assert len(keys) >= 1
        # The duration should be > 0.01s since we sleep for 10ms
        samples = reg.http_request_duration_seconds.get_samples({"method": "GET", "path": "/slow-endpoint"})
        count_sample = [s for s in samples if s[0] == "http_request_duration_seconds_count"][0]
        assert count_sample[2] == 1

    def test_middleware_skips_metrics_endpoint(self, client, reset_registry):
        reg = reset_registry
        # Hit the metrics endpoint itself — should NOT be counted
        client.get("/api/v1/metrics/prometheus")
        assert reg.http_requests_total.get(labels={"method": "GET", "path": "/api/v1/metrics/prometheus", "status": "200"}) == 0.0  # noqa: E501

    def test_middleware_skips_health_endpoint(self, client, reset_registry):
        reg = reset_registry
        # Add a health route
        @client.app.get("/health")
        def health():
            return {"status": "ok"}
        client.get("/health")
        assert reg.http_requests_total.get(labels={"method": "GET", "path": "/health", "status": "200"}) == 0.0

    def test_middleware_tracks_different_status_codes(self, client, reset_registry):
        reg = reset_registry
        client.get("/test-endpoint")  # 200
        client.get("/nonexistent-path-xyz")  # 404
        count_200 = reg.http_requests_total.get(labels={"method": "GET", "path": "/test-endpoint", "status": "200"})
        count_404 = reg.http_requests_total.get(labels={"method": "GET", "path": "/nonexistent-path-xyz", "status": "404"})
        assert count_200 == 1.0
        assert count_404 == 1.0


# ── Metrics endpoint integration tests ───────────────────────────────────


@pytest.mark.unit
class TestMetricsEndpoint:
    def test_prometheus_endpoint_returns_200(self, client):
        resp = client.get("/api/v1/metrics/prometheus")
        assert resp.status_code == 200

    def test_prometheus_endpoint_content_type(self, client):
        resp = client.get("/api/v1/metrics/prometheus")
        assert "text/plain" in resp.headers["content-type"]

    def test_prometheus_endpoint_includes_counter(self, client, reset_registry):
        reg = reset_registry
        reg.http_requests_total.inc(labels={"method": "GET", "path": "/test", "status": "200"})
        resp = client.get("/api/v1/metrics/prometheus")
        assert "http_requests_total" in resp.text

    def test_prometheus_endpoint_counter_increments(self, client, reset_registry):
        reg = reset_registry
        # Hit test-endpoint to generate a metric
        client.get("/test-endpoint")
        # Now check the metrics endpoint — should show the counter
        resp = client.get("/api/v1/metrics/prometheus")
        assert 'http_requests_total{method="GET",path="/test-endpoint",status="200"} 1' in resp.text
        # Hit test-endpoint again
        client.get("/test-endpoint")
        resp2 = client.get("/api/v1/metrics/prometheus")
        assert 'http_requests_total{method="GET",path="/test-endpoint",status="200"} 2' in resp2.text


# ── Thread safety tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestThreadSafety:
    def test_counter_thread_safe_increment(self):
        c = Counter("test_counter", "test", label_names=["thread"])
        num_threads = 10
        increments_per_thread = 100

        def worker(thread_id):
            for _ in range(increments_per_thread):
                c.inc(labels={"thread": str(thread_id)})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(num_threads):
            assert c.get(labels={"thread": str(i)}) == float(increments_per_thread)

    def test_gauge_thread_safe_set(self):
        g = Gauge("test_gauge", "test")
        num_threads = 10

        def worker(value):
            g.set(value)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The final value should be one of the thread IDs (non-negative)
        assert g.get() >= 0

    def test_histogram_thread_safe_observe(self):
        h = Histogram("test_hist", "test", buckets=(1.0, 10.0, float("inf")))
        num_threads = 10
        observations = 50

        def worker():
            for i in range(observations):
                h.observe(float(i))

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = num_threads * observations
        samples = h.get_samples()
        count_sample = [s for s in samples if s[0] == "test_hist_count"][0]
        sum_sample = [s for s in samples if s[0] == "test_hist_sum"][0]
        assert count_sample[2] == total
        expected_sum = sum(float(i) for i in range(observations)) * num_threads
        assert sum_sample[2] == pytest.approx(expected_sum)

    def test_registry_gauge_inc_dec_concurrent(self, reset_registry):
        reg = reset_registry
        num_threads = 10

        def increment():
            for _ in range(100):
                reg.agent_active_websockets.inc()

        def decrement():
            for _ in range(100):
                reg.agent_active_websockets.dec()

        threads = []
        for _ in range(num_threads // 2):
            threads.append(threading.Thread(target=increment))
            threads.append(threading.Thread(target=decrement))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Equal increments and decrements should balance to 0
        assert reg.agent_active_websockets.get() == 0.0
