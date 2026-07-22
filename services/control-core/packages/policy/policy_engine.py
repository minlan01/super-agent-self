"""Policy Engine -- executes security checks before tool execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yaml

from packages.policy import risk_rules
from packages.policy.capability_token import TokenIssuer

logger = structlog.get_logger()

_policy_config_cache: dict[str, Any] | None = None
_policy_config_path: str | None = None
_policy_config_mtime: float = 0.0


@dataclass
class PolicyResult:
    allowed: bool
    reason: str = ""
    risk_level: str = "low"
    requires_approval: bool = False
    token: str | None = None  # Capability token if allowed


class PolicyEngine:
    def __init__(
        self,
        tool_registry: Any,  # ToolRegistry or UnifiedToolRegistry
        token_issuer: TokenIssuer,
        config_path: str = "configs/policy.yaml",
    ):
        self.tool_registry = tool_registry
        self.token_issuer = token_issuer
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        global _policy_config_cache, _policy_config_path, _policy_config_mtime

        path = Path(config_path)
        use_cache = (
            _policy_config_cache is not None
            and _policy_config_path == config_path
            and path.exists()
            and path.stat().st_mtime <= _policy_config_mtime
        )
        if use_cache:
            config = _policy_config_cache
        elif path.exists():
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            _policy_config_cache = config
            _policy_config_path = config_path
            _policy_config_mtime = path.stat().st_mtime
        else:
            config = {}

        policy = config.get("policy", {})
        self.forbidden_tools = policy.get("forbidden_tools", [])
        self.max_allowed_risk = policy.get("max_allowed_risk", "high")
        self.workspace_only = policy.get("workspace_only", True)
        self.forbidden_path_prefixes = policy.get("forbidden_path_prefixes", [])
        self.forbidden_url_patterns = policy.get("forbidden_url_patterns", [])
        self.require_approval_risk_levels = policy.get("require_approval_risk_levels", ["high"])

    def check(self, task_id: str, step_id: str, tool_name: str, args: dict[str, Any], edition: str = "enterprise") -> PolicyResult:
        """Run all policy checks for a tool execution step.

        Checks:
        0. Tool check_fn (if registered via UnifiedToolRegistry)
        1. Tool is registered
        2. Tool is enabled
        3. Tool is not forbidden
        4. Tool is available for edition
        5. Risk level within limits
        6. Path/URL safety checks (if applicable)
        7. Issue capability token
        """
        # Check 0: tool-level check_fn (from decorator registration)
        tool = self.tool_registry.get_tool(tool_name)
        if tool is not None and hasattr(tool, "check_fn") and tool.check_fn is not None:
            ok, reason = tool.check_fn(args)
            if not ok:
                return PolicyResult(allowed=False, reason=f"Tool check_fn rejected: {reason}")

        # Check 1: Tool is registered
        if tool is None:
            return PolicyResult(allowed=False, reason=f"Tool '{tool_name}' not registered")

        # Check 2: Tool is enabled
        if not tool.enabled:
            return PolicyResult(allowed=False, reason=f"Tool '{tool_name}' is disabled")

        # Check 3: Not forbidden
        ok, reason = risk_rules.check_tool_allowed(tool_name, self.forbidden_tools)
        if not ok:
            return PolicyResult(allowed=False, reason=reason)

        # Check 4: Edition check
        if not self.tool_registry.is_available_for_edition(tool_name, edition):
            return PolicyResult(allowed=False, reason=f"Tool '{tool_name}' not available for edition '{edition}'")

        # Check 5: Risk level
        ok, reason = risk_rules.check_risk_level(tool.risk_level, self.max_allowed_risk)
        if not ok:
            return PolicyResult(allowed=False, reason=reason, risk_level=tool.risk_level)

        # Check 6: Path/URL safety
        if tool.category in ("file", "browser"):
            safety_result = self._check_args_safety(tool_name, args, tool.category)
            if safety_result is not None:
                return safety_result

        # Determine if approval needed
        requires_approval = tool.risk_level in self.require_approval_risk_levels

        # P0.5 (G-02 fix): do NOT issue a capability token when approval is
        # required. The token must only be issued AFTER the approval is
        # resolved (by ApprovalService / Orchestrator.resume_after_approval).
        # Previously this was unconditional, allowing high-risk tools to
        # execute before approval — see spec v1.1 §0.2 E-01/E-02.
        if requires_approval:
            logger.info(
                "Policy WAIT_APPROVAL: %s (risk=%s) — token withheld pending approval",
                tool_name, tool.risk_level,
            )
            return PolicyResult(
                allowed=False,   # NOT executable yet
                risk_level=tool.risk_level,
                requires_approval=True,
                reason=f"Tool '{tool_name}' (risk={tool.risk_level}) requires approval before execution",
            )

        # Low/medium risk: issue token immediately
        token = self.token_issuer.issue(task_id, step_id, tool_name, args)
        logger.info("Policy GRANT: %s (risk=%s)", tool_name, tool.risk_level)
        return PolicyResult(
            allowed=True,
            risk_level=tool.risk_level,
            requires_approval=False,
            token=token,
        )

    def _check_args_safety(self, tool_name: str, args: dict, category: str) -> PolicyResult | None:
        """Check path and URL safety in tool arguments."""
        # URL checks for browser tools
        if category == "browser" and "url" in args:
            ok, reason = risk_rules.check_url_allowed(args["url"], self.forbidden_url_patterns)
            if not ok:
                return PolicyResult(allowed=False, reason=reason)

        # Path checks for file tools
        if category == "file":
            path_key = "path" if "path" in args else "output_path"
            if path_key in args:
                ok, reason = risk_rules.check_forbidden_path(args[path_key], self.forbidden_path_prefixes)
                if not ok:
                    return PolicyResult(allowed=False, reason=reason)

        return None
