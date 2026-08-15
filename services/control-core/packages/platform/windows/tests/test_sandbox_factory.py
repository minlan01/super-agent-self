"""Lifecycle and cleanup tests for the task-scoped Windows sandbox factory."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from packages.platform.windows import sandbox_factory

# The factory enforces a Windows-only platform gate before staging; these
# lifecycle tests exercise post-gate behavior and can only run on Windows.
requires_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="sandbox factory requires Windows host"
)


class _FakeBroker:
    def __init__(self, *, fail_initialize: bool = False, fail_close: bool = False):
        self.fail_initialize = fail_initialize
        self.fail_close = fail_close
        self.initialized = False
        self.closed = False

    def initialize(self):
        if self.fail_initialize:
            raise RuntimeError("forced broker initialization failure")
        self.initialized = True
        return object()

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("forced broker close failure")


class _FakeSandbox:
    def __init__(self, broker, *, fail_create=False, fail_run=False, fail_kill=False):
        self.broker = broker
        self.fail_create = fail_create
        self.fail_run = fail_run
        self.fail_kill = fail_kill
        self.created = False
        self.killed = False

    async def create(self, _profile):
        if self.fail_create:
            raise RuntimeError("forced sandbox create failure")
        self.created = True
        return object()

    async def run(self, _handle, _executable, _args, *, cwd, env, timeout_sec):
        assert cwd
        assert isinstance(env, dict)
        assert timeout_sec > 0
        if self.fail_run:
            raise RuntimeError("forced sandbox run failure")
        return 0, b"ok", b""

    async def kill_tree(self, _handle):
        self.killed = True
        if self.fail_kill:
            raise RuntimeError("forced sandbox kill failure")


@requires_windows
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["initialize", "create", "run", "kill", "close"],
)
async def test_factory_cleans_staged_runtime_after_every_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
):
    """Runtime staging must not leak when any factory lifecycle step fails."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = workspace / "trusted.exe"
    executable.write_bytes(b"not-a-real-pe-for-copy-test")
    created_runtime: list[Path] = []
    brokers: list[_FakeBroker] = []
    sandboxes: list[_FakeSandbox] = []

    def make_temp(*, prefix: str) -> str:
        runtime = tmp_path / f"{prefix}fixture"
        runtime.mkdir()
        created_runtime.append(runtime)
        return str(runtime)

    def make_broker(_workspace: str, *, runtime_roots=()):
        assert runtime_roots
        broker = _FakeBroker(
            fail_initialize=failure == "initialize",
            fail_close=failure == "close",
        )
        brokers.append(broker)
        return broker

    def make_sandbox(broker):
        sandbox = _FakeSandbox(
            broker,
            fail_create=failure == "create",
            fail_run=failure == "run",
            fail_kill=failure == "kill",
        )
        sandboxes.append(sandbox)
        return sandbox

    monkeypatch.setattr(sandbox_factory.tempfile, "mkdtemp", make_temp)
    monkeypatch.setattr(sandbox_factory, "create_default_isolation", make_broker)
    monkeypatch.setattr(sandbox_factory, "WindowsProcessSandbox", make_sandbox)

    with pytest.raises(Exception):
        await sandbox_factory.WindowsProcessSandboxFactory.execute(
            workspace_root=str(workspace),
            executable=str(executable),
            args=(),
            cwd=str(workspace),
            env={},
            timeout_sec=2,
            stage_executable=True,
        )

    assert created_runtime
    assert all(not runtime.exists() for runtime in created_runtime)
    assert brokers and brokers[0].closed is True
    if sandboxes:
        assert sandboxes[0].killed is (failure in {"run", "kill", "close"})
