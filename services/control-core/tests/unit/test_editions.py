"""Unit tests for edition config API routes — list editions and get edition detail."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.api_server.routes.editions import get_edition, list_editions

# ── Helpers ───────────────────────────────────────────────────────────────


def _mock_manager(editions=None):
    """Build a mock EditionManager with configurable edition data."""
    mgr = MagicMock()

    if editions is None:
        editions = {
            "enterprise": {
                "edition": "enterprise",
                "name": "Enterprise Edition",
                "description": "Enterprise-grade platform",
                "tools": {
                    "enabled": ["browser.open", "file.read"],
                    "disabled": ["shell.run"],
                },
                "policy": {"max_risk_level": "medium"},
                "approval": {"auto_approve_low_risk": True},
                "memory": {
                    "types": ["execution_experience"],
                    "retention_days": 90,
                },
            },
            "personal": {
                "edition": "personal",
                "name": "Personal Jarvis Edition",
                "description": "Personal AI assistant",
                "tools": {
                    "enabled": ["file.search"],
                    "disabled": [],
                },
                "policy": {"max_risk_level": "high"},
                "approval": {"auto_approve_low_risk": False},
                "memory": {
                    "types": ["user_preference"],
                    "retention_days": 365,
                },
            },
        }

    mgr.list_editions.return_value = list(editions.keys())

    for name, cfg in editions.items():
        mgr.get_name.return_value = None  # will be configured per-call below
        mgr.get_description.return_value = None

    # Configure per-edition return values using side_effect lambdas
    names = {e: c.get("name", e.title()) for e, c in editions.items()}
    descs = {e: c.get("description", "") for e, c in editions.items()}
    enabled = {e: c.get("tools", {}).get("enabled", []) for e, c in editions.items()}
    disabled = {e: c.get("tools", {}).get("disabled", []) for e, c in editions.items()}
    risk = {e: c.get("policy", {}).get("max_risk_level", "medium") for e, c in editions.items()}
    auto = {e: c.get("approval", {}).get("auto_approve_low_risk", True) for e, c in editions.items()}
    mem_types = {e: c.get("memory", {}).get("types", []) for e, c in editions.items()}
    retention = {e: c.get("memory", {}).get("retention_days", 90) for e, c in editions.items()}

    mgr.get_name.side_effect = lambda e: names.get(e, e.title())
    mgr.get_description.side_effect = lambda e: descs.get(e, "")
    mgr.get_config.side_effect = lambda e: editions.get(e, {})
    mgr.get_enabled_tools.side_effect = lambda e: enabled.get(e, [])
    mgr.get_disabled_tools.side_effect = lambda e: disabled.get(e, [])
    mgr.get_max_risk_level.side_effect = lambda e: risk.get(e, "medium")
    mgr.auto_approve_low_risk.side_effect = lambda e: auto.get(e, True)
    mgr.get_memory_types.side_effect = lambda e: mem_types.get(e, [])
    mgr.get_retention_days.side_effect = lambda e: retention.get(e, 90)
    mgr.is_personal.side_effect = lambda e: e == "personal"
    mgr.is_enterprise.side_effect = lambda e: e == "enterprise"

    return mgr


# ── list_editions ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestListEditions:
    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_returns_all_editions(self, mock_get_mgr):
        """list_editions returns all configured editions."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = list_editions()
        assert result["success"] is True
        assert len(result["data"]) == 2

        edition_names = [item["edition"] for item in result["data"]]
        assert "enterprise" in edition_names
        assert "personal" in edition_names

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_returns_name_and_description(self, mock_get_mgr):
        """Each edition entry includes name and description."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = list_editions()
        for item in result["data"]:
            assert "name" in item
            assert "description" in item

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_empty_when_no_editions(self, mock_get_mgr):
        """Returns empty list when no editions are configured."""
        mgr = _mock_manager(editions={})
        mock_get_mgr.return_value = mgr

        result = list_editions()
        assert result["success"] is True
        assert result["data"] == []


# ── get_edition ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetEdition:
    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_get_enterprise_edition(self, mock_get_mgr):
        """get_edition returns full config for enterprise."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = get_edition(edition="enterprise")
        assert result["success"] is True
        assert result["data"]["edition"] == "enterprise"
        assert result["data"]["is_enterprise"] is True
        assert result["data"]["is_personal"] is False
        assert "tools" in result["data"]
        assert "policy" in result["data"]
        assert "memory" in result["data"]

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_get_personal_edition(self, mock_get_mgr):
        """get_edition returns full config for personal."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = get_edition(edition="personal")
        assert result["success"] is True
        assert result["data"]["edition"] == "personal"
        assert result["data"]["is_personal"] is True
        assert result["data"]["is_enterprise"] is False

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_get_edition_not_found(self, mock_get_mgr):
        """Non-existent edition raises 404."""
        mgr = _mock_manager()
        mgr.get_config.return_value = {}
        # get_config returns empty dict for unknown edition
        mock_get_mgr.return_value = mgr

        # Empty dict is falsy in the route's `if not config` check
        with pytest.raises(HTTPException) as exc_info:
            get_edition(edition="nonexistent")
        assert exc_info.value.status_code == 404

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_get_edition_has_tools_section(self, mock_get_mgr):
        """Edition detail includes enabled/disabled tools."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = get_edition(edition="enterprise")
        tools = result["data"]["tools"]
        assert "enabled" in tools
        assert "disabled" in tools
        assert "browser.open" in tools["enabled"]

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_get_edition_has_policy_section(self, mock_get_mgr):
        """Edition detail includes policy settings."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = get_edition(edition="enterprise")
        policy = result["data"]["policy"]
        assert "max_risk_level" in policy
        assert "auto_approve_low_risk" in policy

    @patch("apps.api_server.routes.editions._get_edition_manager")
    def test_get_edition_has_memory_section(self, mock_get_mgr):
        """Edition detail includes memory settings."""
        mgr = _mock_manager()
        mock_get_mgr.return_value = mgr

        result = get_edition(edition="enterprise")
        memory = result["data"]["memory"]
        assert "types" in memory
        assert "retention_days" in memory
        assert memory["retention_days"] == 90
