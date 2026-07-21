"""Command Safety Checker — detects dangerous commands and prompt injection patterns."""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


class CommandSafetyChecker:
    """Multi-layer safety checker for shell commands and text content.

    Checks for:
    - Dangerous command patterns (rm -rf, chmod 777, etc.)
    - Prompt injection patterns (ignore instructions, system prompt override, etc.)
    - Data exfiltration patterns (curl ${, base64 decode to pipe, etc.)
    - Unicode normalization bypasses
    """

    DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"rm\s+.*(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-r\b.*-f\b|-f\b.*-r\b|--recursive\b.*--force\b)", re.I),
        re.compile(r"rm\s+-rf\s+/", re.I),
        re.compile(r"rm\s+-rf\s+--no-preserve-root", re.I),
        re.compile(r"chmod\s+777", re.I),
        re.compile(r"mkfs", re.I),
        re.compile(r"curl.*\|\s*(\bsh\b|/bin/sh|/usr/bin/sh|/bin/bash|/usr/bin/bash|\bbash\b)", re.I),
        re.compile(r"wget.*\|\s*(\bsh\b|/bin/sh|/usr/bin/sh|/bin/bash|/usr/bin/bash|\bbash\b)", re.I),
        re.compile(r"dd\s+if=", re.I),
        re.compile(r"git\s+push\s+--force", re.I),
        re.compile(r"git\s+reset\s+--hard", re.I),
        re.compile(r":\(\)\{.*:\|:&"),
        re.compile(r"shutdown", re.I),
        re.compile(r"reboot", re.I),
        re.compile(r"format\s+[A-Za-z]:", re.I),
        re.compile(r"del\s+/s\s+/q\s+C:", re.I),
        re.compile(r"rd\s+/s\s+/q", re.I),
        re.compile(r"taskkill\s+/f", re.I),
        re.compile(r"reg\s+delete", re.I),
        re.compile(r"net\s+user", re.I),
        re.compile(r"DROP\s+TABLE", re.I),
        re.compile(r"DELETE\s+FROM\s+\w+\s*;", re.I),
        re.compile(r"TRUNCATE\s+TABLE", re.I),
        re.compile(r">\s*/dev/sd", re.I),
        re.compile(r"mv\s+/.*\s+/dev/null", re.I),
        re.compile(r"python\s+-c\s+.*(?:os\.(?:system|popen)|subprocess\.)", re.I),
        re.compile(r"perl\s+-e\s+.*system\s*\(", re.I),
        re.compile(r"ruby\s+-e\s+.*system\s*\(", re.I),
        re.compile(r"node\s+-e\s+.*require\s*\(\s*['\"]child_process", re.I),
    ]

    INJECTION_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"ignore\s+previous\s+instructions", re.I),
        re.compile(r"system\s+prompt\s+override", re.I),
        re.compile(r"forget\s+everything", re.I),
        re.compile(r"you\s+are\s+now\s+a", re.I),
        re.compile(r"new\s+instructions?\s*:", re.I),
        re.compile(r"curl\s+\$\{", re.I),
        re.compile(r"base64\s+-d\s*\|", re.I),
        re.compile(r"base64\s+--decode\s*\|", re.I),
        re.compile(r"echo\s+.*\|\s*base64\s+-d\s*\|", re.I),
        re.compile(r"eval\s*\$\(", re.I),
        re.compile(r"eval\s*\$\s*\(", re.I),
        re.compile(r"\$\(\s*curl", re.I),
        re.compile(r"\$\s*\(\s*curl", re.I),
        re.compile(r"wget\s+.*\|\s*sh", re.I),
    ]

    def check_command(self, command: str) -> tuple[bool, str]:
        """Check a command for dangerous patterns. Returns (safe, reason).

        Normalizes Unicode to NFKC form to prevent bypass via homoglyphs.
        """
        # Normalize Unicode to prevent bypass
        normalized = unicodedata.normalize("NFKC", command)

        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.search(normalized):
                return False, f"Dangerous pattern detected: {pattern.pattern}"

        return True, "ok"

    def check_injection(self, text: str) -> tuple[bool, str]:
        """Check text for prompt injection and data exfiltration patterns."""
        normalized = unicodedata.normalize("NFKC", text)

        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(normalized):
                return False, f"Injection pattern detected: {pattern.pattern}"

        return True, "ok"

    def check_all(self, command: str) -> tuple[bool, str]:
        """Run all safety checks. Returns (safe, reason)."""
        safe, reason = self.check_command(command)
        if not safe:
            return False, reason
        safe, reason = self.check_injection(command)
        if not safe:
            return False, reason
        return True, "ok"
