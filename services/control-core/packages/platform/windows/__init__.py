"""Windows P1 platform implementations.

The modules import Windows bindings lazily so contract inspection and Linux
development can import the package without touching pywin32 or Win32 APIs.
"""

from .adapter import WindowsPlatformAdapter
from .capture_wgc import WindowsGraphicsCapture
from .local_ipc import (
    MAX_MESSAGE_SIZE,
    PIPE_NAME,
    RATE_LIMIT_PER_SEC,
    WindowsNamedPipeIpc,
)
from .process_sandbox import WindowsProcessSandbox, WindowsSandboxHandle
from .secret_store import CRED_PREFIX, WindowsCredentialStore
from .session_monitor import WindowsSessionMonitor
from .uia import WindowsUIAWindowProvider

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
