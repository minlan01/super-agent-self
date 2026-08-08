"""P3.10A/B tests: parameterized process execution and ConPTY contracts."""

from __future__ import annotations

import os

import pytest

from packages.platform.windows.process_tools import (
    PROCESS_EXECUTE_VERSION,
    SHELL_INTERPRETERS,
    ProcessExecuteRequest,
    ProcessExecuteResult,
)
from packages.platform.windows.conpty import (
    TERMINAL_SESSION_VERSION,
    ConPTYNotImplemented,
    ResizeRequest,
    SessionState,
    TerminalMessage,
    TerminalSession,
    is_conpty_available,
)


class TestProcessExecuteRequest:
    """P3.10A: Parameterized process execution request validation."""

    def test_valid_request_from_dict(self):
        """Valid request should parse successfully."""
        req = ProcessExecuteRequest.from_dict({
            "executable": r"C:\Windows\System32\where.exe",
            "args": ["python"],
            "cwd": r"D:\workspace\task-1",
            "timeout_sec": 30,
        })
        assert req.executable == r"C:\Windows\System32\where.exe"
        assert req.args == ("python",)
        assert req.version == PROCESS_EXECUTE_VERSION

    def test_rejects_shell_interpreters(self, tmp_path):
        """process.execute must refuse shell interpreters."""
        for shell in ["cmd.exe", "powershell.exe", "bash", "sh", "python.exe"]:
            req = ProcessExecuteRequest(
                executable=f"C:\\Windows\\System32\\{shell}",
                args=(),
                cwd=str(tmp_path),
            )
            with pytest.raises(Exception, match="shell interpreter"):
                req.validate_security(str(tmp_path))

    def test_rejects_relative_executable(self, tmp_path):
        """executable must be absolute path."""
        req = ProcessExecuteRequest(
            executable="where.exe",
            args=(),
            cwd=str(tmp_path),
        )
        with pytest.raises(Exception, match="absolute path"):
            req.validate_security(str(tmp_path))

    def test_rejects_cwd_outside_workspace(self, tmp_path):
        """cwd must resolve inside workspace_root."""
        req = ProcessExecuteRequest(
            executable=r"C:\Windows\System32\where.exe",
            args=(),
            cwd=r"C:\Windows",  # outside workspace
        )
        with pytest.raises(Exception, match="inside workspace"):
            req.validate_security(str(tmp_path))

    def test_timeout_must_be_positive(self):
        """timeout_sec must be positive."""
        with pytest.raises(ValueError):
            ProcessExecuteRequest.from_dict({
                "executable": "/bin/echo",
                "args": [],
                "cwd": "/tmp",
                "timeout_sec": -1,
            })

    def test_args_must_be_strings(self):
        """All args must be strings."""
        with pytest.raises(TypeError):
            ProcessExecuteRequest.from_dict({
                "executable": "/bin/echo",
                "args": [1, 2, 3],
                "cwd": "/tmp",
            })

    def test_env_must_be_dict_or_none(self):
        """env must be a dict or None."""
        with pytest.raises(TypeError):
            ProcessExecuteRequest.from_dict({
                "executable": "/bin/echo",
                "args": [],
                "cwd": "/tmp",
                "env": "not a dict",
            })

    def test_version_check(self):
        """Unsupported version must be rejected."""
        with pytest.raises(ValueError, match="unsupported API version"):
            ProcessExecuteRequest.from_dict({
                "executable": "/bin/echo",
                "args": [],
                "cwd": "/tmp",
                "version": "2.0",
            })

    def test_request_is_frozen(self, tmp_path):
        """Request should be immutable."""
        req = ProcessExecuteRequest(
            executable="/bin/echo",
            args=(),
            cwd=str(tmp_path),
        )
        with pytest.raises((AttributeError, TypeError)):
            req.executable = "/bin/cat"  # type: ignore[misc]


class TestConPTYContract:
    """P3.10B: ConPTY session contract — runs everywhere."""

    def test_terminal_session_states(self):
        """SessionState enum should cover all lifecycle states."""
        states = {s.value for s in SessionState}
        expected = {"created", "running", "resized", "signalled", "closed", "timeout", "error"}
        assert expected.issubset(states)

    def test_terminal_session_creation(self):
        """TerminalSession should be creatable with required fields."""
        session = TerminalSession(
            session_id="s1",
            owner_principal_id="user-1",
            workspace_id="ws-1",
            executable=r"C:\Windows\System32\cmd.exe",
            args=("/k",),
        )
        assert session.state == SessionState.CREATED
        assert session.exit_code is None
        assert session.protocol_version == TERMINAL_SESSION_VERSION

    def test_resize_request_validation(self):
        """ResizeRequest should validate cols/rows bounds."""
        ResizeRequest(cols=80, rows=24)  # valid
        ResizeRequest(cols=1, rows=1)   # minimum

        with pytest.raises(ValueError):
            ResizeRequest(cols=0, rows=24)
        with pytest.raises(ValueError):
            ResizeRequest(cols=80, rows=0)
        with pytest.raises(ValueError):
            ResizeRequest(cols=501, rows=24)

    def test_terminal_message_types(self):
        """TerminalMessage should support all message types."""
        for msg_type in ["input", "output", "resize", "signal", "close", "error", "heartbeat"]:
            msg = TerminalMessage(msg_type=msg_type, payload=b"test")
            assert msg.msg_type == msg_type

    def test_conpty_not_implemented_error(self):
        """ConPTYNotImplemented should be a CapabilityUnavailable."""
        err = ConPTYNotImplemented()
        assert "conpty" in str(err).lower() or "not implemented" in str(err).lower()

    def test_is_conpty_available_returns_bool(self):
        """is_conpty_available should return a boolean."""
        result = is_conpty_available()
        assert isinstance(result, bool)

    def test_shell_interpreters_blocklist_complete(self):
        """SHELL_INTERPRETERS should cover common interpreters."""
        expected = {"cmd.exe", "powershell.exe", "bash", "sh", "python.exe"}
        normalized = {s.lower() for s in SHELL_INTERPRETERS}
        for interpreter in expected:
            assert interpreter.lower() in normalized, f"{interpreter} missing from blocklist"
