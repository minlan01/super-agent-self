"""Tests for monitoring configuration files.

Validates that Prometheus config, Grafana dashboard JSON, docker-compose
monitoring overlay, and provisioning files are well-formed and reference
the correct metric names from the platform.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

MONITORING_DIR = Path(__file__).resolve().parent.parent.parent / "monitoring"


# ── Helpers ──────────────────────────────────────────────────────────────


def _load_yaml(relative_path: str) -> dict:
    path = MONITORING_DIR / relative_path
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(relative_path: str) -> dict:
    path = MONITORING_DIR / relative_path
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Prometheus config ───────────────────────────────────────────────────


class TestPrometheusConfig:
    """Validate prometheus.yml structure."""

    def test_valid_yaml(self):
        config = _load_yaml("prometheus/prometheus.yml")
        assert isinstance(config, dict)

    def test_scrape_interval(self):
        config = _load_yaml("prometheus/prometheus.yml")
        assert config["global"]["scrape_interval"] == "15s"
        assert config["global"]["evaluation_interval"] == "15s"

    def test_scrape_config_targets_myself_agent(self):
        config = _load_yaml("prometheus/prometheus.yml")
        scrape_configs = config["scrape_configs"]
        assert len(scrape_configs) >= 1
        job = scrape_configs[0]
        assert job["job_name"] == "myself-agent"
        assert job["metrics_path"] == "/api/v1/metrics/prometheus"

    def test_target_uses_host_docker_internal(self):
        config = _load_yaml("prometheus/prometheus.yml")
        targets = config["scrape_configs"][0]["static_configs"][0]["targets"]
        assert any("host.docker.internal:8000" in t for t in targets)


# ── Grafana dashboard ───────────────────────────────────────────────────


class TestGrafanaDashboard:
    """Validate dashboard.json structure and metric references."""

    EXPECTED_PANEL_TITLES = [
        "HTTP Request Rate",
        "Request Latency",
        "Task Completion Rate",
        "Active WebSocket Connections",
        "Active DB Connections",
        "HTTP Error Rate (5xx)",
    ]

    EXPECTED_METRICS = [
        "http_requests_total",
        "http_request_duration_seconds_bucket",
        "agent_tasks_total",
        "agent_active_websockets",
        "agent_db_connections_active",
    ]

    @pytest.fixture()
    def dashboard(self) -> dict:
        return _load_json("grafana/dashboard.json")

    def test_valid_json(self, dashboard: dict):
        assert isinstance(dashboard, dict)
        assert dashboard.get("title") == "Myself-Agent Platform"

    def test_has_uid(self, dashboard: dict):
        assert "uid" in dashboard
        assert dashboard["uid"] == "myself-agent-platform"

    def test_has_minimum_six_panels(self, dashboard: dict):
        panels = dashboard["panels"]
        assert len(panels) >= 6

    def test_expected_panel_titles_present(self, dashboard: dict):
        titles = [p["title"] for p in dashboard["panels"]]
        for expected in self.EXPECTED_PANEL_TITLES:
            assert expected in titles, f"Missing panel: {expected}"

    def test_panels_reference_correct_metrics(self, dashboard: dict):
        """Every panel target expr should reference at least one known metric."""
        all_exprs: list[str] = []
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                all_exprs.append(expr)
        combined = " ".join(all_exprs)
        for metric in self.EXPECTED_METRICS:
            assert metric in combined, f"Dashboard does not reference metric: {metric}"

    def test_has_datasource_template_variable(self, dashboard: dict):
        templates = dashboard.get("templating", {}).get("list", [])
        ds_names = [t["name"] for t in templates]
        assert "datasource" in ds_names

    def test_panels_have_prometheus_datasource(self, dashboard: dict):
        for panel in dashboard["panels"]:
            ds = panel.get("datasource", {})
            assert ds.get("type") == "prometheus"

    def test_error_rate_panel_filters_5xx(self, dashboard: dict):
        """The HTTP Error Rate panel should filter for 5xx statuses."""
        for panel in dashboard["panels"]:
            if "Error" in panel["title"]:
                exprs = [t["expr"] for t in panel.get("targets", [])]
                combined = " ".join(exprs)
                assert 'status=~"5.."' in combined
                return
        pytest.fail("No error rate panel found")


# ── Docker Compose monitoring ───────────────────────────────────────────


class TestDockerComposeMonitoring:
    """Validate docker-compose.monitoring.yml."""

    @pytest.fixture()
    def compose(self) -> dict:
        return _load_yaml("docker-compose.monitoring.yml")

    def test_valid_yaml(self, compose: dict):
        assert isinstance(compose, dict)
        assert "services" in compose

    def test_has_prometheus_service(self, compose: dict):
        assert "prometheus" in compose["services"]
        prom = compose["services"]["prometheus"]
        assert prom["image"] == "prom/prometheus:v2.53.0"
        assert "9090:9090" in prom["ports"]

    def test_has_grafana_service(self, compose: dict):
        assert "grafana" in compose["services"]
        grafana = compose["services"]["grafana"]
        assert grafana["image"] == "grafana/grafana:11.1.0"
        assert "3001:3000" in grafana["ports"]

    def test_grafana_depends_on_prometheus(self, compose: dict):
        grafana = compose["services"]["grafana"]
        assert "prometheus" in grafana.get("depends_on", [])

    def test_prometheus_has_host_docker_internal(self, compose: dict):
        prom = compose["services"]["prometheus"]
        extra_hosts = prom.get("extra_hosts", [])
        assert any("host.docker.internal" in eh for eh in extra_hosts)

    def test_grafana_mounts_provisioning(self, compose: dict):
        grafana = compose["services"]["grafana"]
        volumes = grafana.get("volumes", [])
        vol_paths = [v.split(":")[0] for v in volumes]
        assert any("provisioning" in p for p in vol_paths)

    def test_has_named_volumes(self, compose: dict):
        volumes = compose.get("volumes", {})
        assert "prometheus-data" in volumes
        assert "grafana-storage" in volumes


# ── Provisioning files ──────────────────────────────────────────────────


class TestProvisioningFiles:
    """Validate Grafana provisioning configs."""

    def test_datasource_provisioning_valid_yaml(self):
        ds = _load_yaml("grafana/provisioning/datasources/prometheus.yml")
        assert ds["apiVersion"] == 1
        datasources = ds["datasources"]
        assert len(datasources) >= 1
        assert datasources[0]["type"] == "prometheus"
        assert datasources[0]["url"] == "http://prometheus:9090"
        assert datasources[0]["isDefault"] is True

    def test_dashboard_provisioning_valid_yaml(self):
        dp = _load_yaml("grafana/provisioning/dashboards/dashboard.yml")
        assert dp["apiVersion"] == 1
        providers = dp["providers"]
        assert len(providers) >= 1
        assert providers[0]["type"] == "file"
        assert "dashboards" in providers[0]["options"]["path"]
