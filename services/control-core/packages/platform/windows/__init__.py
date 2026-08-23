"""Windows P1 platform implementations with lazy public exports."""

from __future__ import annotations

import importlib

__all__ = [
    "CRED_PREFIX",
    "MAX_MESSAGE_SIZE",
    "PIPE_NAME",
    "RATE_LIMIT_PER_SEC",
    "WindowsCredentialStore",
    "WindowsGraphicsCapture",
    "WindowsNamedPipeIpc",
    "WindowsPlatformAdapter",
    "WindowsProcessSandbox",
    "WindowsSandboxHandle",
    "WindowsSessionMonitor",
    "WindowsUIAWindowProvider",
]

_EXPORT_MODULES = {
    "CRED_PREFIX": "packages.platform.windows.secret_store",
    "MAX_MESSAGE_SIZE": "packages.platform.windows.local_ipc",
    "PIPE_NAME": "packages.platform.windows.local_ipc",
    "RATE_LIMIT_PER_SEC": "packages.platform.windows.local_ipc",
    "WindowsCredentialStore": "packages.platform.windows.secret_store",
    "WindowsGraphicsCapture": "packages.platform.windows.capture_wgc",
    "WindowsNamedPipeIpc": "packages.platform.windows.local_ipc",
    "WindowsPlatformAdapter": "packages.platform.windows.adapter",
    "WindowsProcessSandbox": "packages.platform.windows.process_sandbox",
    "WindowsSandboxHandle": "packages.platform.windows.process_sandbox",
    "WindowsSessionMonitor": "packages.platform.windows.session_monitor",
    "WindowsUIAWindowProvider": "packages.platform.windows.uia",
}


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
