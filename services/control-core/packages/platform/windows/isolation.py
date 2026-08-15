"""P3.9 Complete Windows isolation boundary.

Extends the P1 Job Object sandbox with:
1. Restricted token / AppContainer profile (no admin inheritance)
2. Workspace ACL (deny access outside task workspace)
3. Minimal environment variable whitelist
4. Secret broker (one-time, per-tool+task bound secret handle)
5. Egress broker (default-deny network with audited allowlist)
6. Fail-closed initialization

This module does NOT replace WindowsProcessSandbox — it wraps it with
additional security boundaries. The ProcessSandbox contract still uses
Job Objects for process tree management and resource limits.

Security invariants:
- If any isolation initialization fails, execution is blocked (fail-closed)
- Runner cannot read Control DB, workspace-external files, host credentials
- Default-deny network egress; allowlist entries are audited
- Environment variables are minimal whitelist, never full os.environ
- Secrets are one-time handles bound to tool+task, never bulk Credential Manager access
"""

from __future__ import annotations

import ctypes
import logging
import os
import stat
import sys
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any

from packages.platform.shared.errors import SandboxUnavailable

from ._errors import UnsupportedPlatformError

logger = logging.getLogger(__name__)

# Win32 constants for security isolation
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008

DISABLE_MAX_PRIVILEGE = 0x1
LUA_TOKEN = 0x4
HRESULT_ALREADY_EXISTS = 0x800700B7

# Administrator-equivalent groups that must be deny-only on the runner token.
_ADMINISTRATIVE_SIDS: frozenset[str] = frozenset({
    "S-1-5-114",       # Local account and member of Administrators group
    "S-1-5-32-544",    # Administrators
    "S-1-5-32-547",    # Power Users
    "S-1-5-32-548",    # Account Operators
    "S-1-5-32-549",    # Server Operators
    "S-1-5-32-550",    # Print Operators
    "S-1-5-32-551",    # Backup Operators
    "S-1-5-32-556",    # Network Configuration Operators
})

# Environment variable whitelist — only these are passed to sandboxed processes
DEFAULT_ENV_WHITELIST: frozenset[str] = frozenset({
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
})

# Secrets that must NEVER appear in environment
SECRET_ENV_BLOCKLIST: frozenset[str] = frozenset({
    "PASSWORD", "SECRET", "TOKEN", "API_KEY", "APIKEY",
    "ACCESS_TOKEN", "REFRESH_TOKEN", "PRIVATE_KEY",
    "CREDENTIAL", "AUTH", "AUTHORIZATION",
    "AWS_SECRET_ACCESS_KEY", "AZURE_CLIENT_SECRET",
    "DATABASE_URL", "REDIS_URL",
})


@dataclass(slots=True, frozen=True)
class IsolationConfig:
    """Configuration for the complete isolation boundary."""

    workspace_root: str
    runtime_roots: tuple[str, ...] = ()
    deny_paths: tuple[str, ...] = ()
    env_whitelist: frozenset[str] = DEFAULT_ENV_WHITELIST
    egress_allowlist: tuple[str, ...] = ()  # host:port entries
    enable_restricted_token: bool = True
    enable_appcontainer: bool = True
    enable_workspace_acl: bool = True
    enable_egress_filter: bool = True
    max_secret_lifetime_sec: int = 300


@dataclass(slots=True)
class SecretHandle:
    """One-time, per-tool+task bound secret handle.

    The actual secret value is never stored in environment variables,
    tool args, or logs. The handle is consumed exactly once.
    """

    handle_id: str
    tool_name: str
    task_id: str
    created_at: float
    expires_at: float = float("inf")
    consumed: bool = False
    _value: str | None = field(default=None, repr=False, compare=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    def consume(self) -> str:
        """Consume the secret handle — returns the value, marks as consumed."""
        return self.consume_at(time.monotonic())

    def consume_at(self, now: float) -> str:
        """Atomically consume the value at a supplied monotonic timestamp."""

        with self._lock:
            if self.consumed:
                raise SandboxUnavailable("secret handle already consumed")
            if now >= self.expires_at:
                self.consumed = True
                self._value = None
                raise SandboxUnavailable("secret handle expired")
            if self._value is None:
                self.consumed = True
                raise SandboxUnavailable("secret handle has no value")
            self.consumed = True
            value = self._value
            self._value = None
            return value

    def clear(self) -> None:
        """Invalidate the handle and release its in-memory value."""

        with self._lock:
            self.consumed = True
            self._value = None


@dataclass(slots=True)
class EgressRule:
    """A single network egress rule."""

    host: str  # hostname or IP
    port: int
    protocol: str = "tcp"  # tcp | udp
    reason: str = ""  # audit reason
    approved_by: str = ""  # approver principal


@dataclass(slots=True)
class IsolationBoundary:
    """The complete isolation boundary applied to a sandboxed process.

    This is an immutable record of the security constraints applied.
    """

    config: IsolationConfig
    restricted_token_applied: bool = False
    appcontainer_applied: bool = False
    workspace_acl_applied: bool = False
    runtime_acl_applied: bool = False
    appcontainer_profile_name: str | None = None
    appcontainer_sid: str | None = None
    egress_rules: tuple[EgressRule, ...] = ()
    env_vars_blocked: int = 0
    secrets_issued: list[str] = field(default_factory=list)
    initialization_verified: bool = False


@dataclass(slots=True, frozen=True)
class _AclSnapshot:
    path: str
    original_sddl: str
    was_protected: bool
    original_descriptor: Any


class _SID_AND_ATTRIBUTES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("Sid", wintypes.LPVOID),
        ("Attributes", wintypes.DWORD),
    ]


class WindowsIsolationBroker:
    """P3.9 isolation boundary broker.

    Applies security constraints beyond what Job Objects provide:
    - Restricted token (strips admin SID, removes privileges)
    - Workspace ACL (file system access control)
    - Environment variable filtering
    - Secret broker (one-time handles)
    - Egress broker (default-deny network)

    All initialization failures are fail-closed: if any step fails,
    the process is NOT started.
    """

    def __init__(self, config: IsolationConfig) -> None:
        self.config = config
        self._secret_handles: dict[str, SecretHandle] = {}
        self._boundary: IsolationBoundary | None = None
        self._restricted_token: Any | None = None
        self._appcontainer_profile_name: str | None = None
        self._appcontainer_sid_ptr = 0
        self._appcontainer_sid_text: str | None = None
        self._profile_created_by_broker = False
        self._workspace_acl_snapshot: _AclSnapshot | None = None
        self._workspace_acl_snapshots: dict[str, _AclSnapshot] = {}
        self._runtime_acl_snapshots: dict[str, _AclSnapshot] = {}
        self._active_launches = 0
        self._accepting_launches = False
        self._cleanup_pending = False
        self._closed = False
        self._state_lock = threading.RLock()

    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError(
                "Windows isolation broker requires Windows"
            )

    def initialize(self) -> IsolationBoundary:
        """Initialize the isolation boundary.

        All steps must succeed for the boundary to be considered active.
        Any failure raises SandboxUnavailable (fail-closed).
        """
        self._require_windows()

        with self._state_lock:
            if self._boundary is not None and self._boundary.initialization_verified:
                return self._boundary
            if self._closed:
                raise SandboxUnavailable("isolation broker is closed")
            if self._cleanup_pending:
                raise SandboxUnavailable(
                    "isolation cleanup is pending; call close() before reinitializing"
                )

            boundary = IsolationBoundary(config=self.config)
            self._boundary = boundary
            try:
                self._validate_initialization_config()
                if self.config.enable_restricted_token:
                    boundary.restricted_token_applied = self._apply_restricted_token()

                if self.config.enable_appcontainer:
                    boundary.appcontainer_applied = self._create_appcontainer_profile()
                    boundary.appcontainer_profile_name = self._appcontainer_profile_name
                    boundary.appcontainer_sid = self._appcontainer_sid_text

                if self.config.enable_workspace_acl:
                    self._ensure_sandbox_temp_directory()
                    self._ensure_sandbox_local_app_data()
                    boundary.workspace_acl_applied = self._apply_workspace_acl()

                if self.config.runtime_roots:
                    boundary.runtime_acl_applied = self._apply_runtime_acls()

                boundary.initialization_verified = True
                self._accepting_launches = True
            except Exception as exc:
                boundary.initialization_verified = False
                self._accepting_launches = False
                cleanup_errors = self._rollback_initialization()
                self._boundary = None
                details = f"; cleanup errors: {'; '.join(cleanup_errors)}" if cleanup_errors else ""
                logger.error("Isolation initialization failed (fail-closed): %s", exc)
                raise SandboxUnavailable(
                    f"isolation initialization failed: {exc}{details}"
                ) from exc

            return boundary

    def _apply_restricted_token(self) -> bool:
        """Create and retain a verified primary token for the runner.

        Uses CreateRestrictedToken to:
        - Disable all privileges (DISABLE_MAX_PRIVILEGE)
        - Mark administrator-equivalent groups deny-only
        - Add the current effective identity/groups as restricting SIDs

        The token is retained by the broker for the process-launch layer. This
        method does not change the token of the current control-core process.

        Returns True if a restricted primary token was created and verified.
        Raises SandboxUnavailable on failure.
        """
        self._require_windows()

        source_token: Any | None = None
        restricted_token: Any | None = None
        try:
            import win32api
            import win32security

            source_token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY,
            )
            user_sid, _attributes = win32security.GetTokenInformation(
                source_token,
                win32security.TokenUser,
            )
            source_groups = win32security.GetTokenInformation(
                source_token,
                win32security.TokenGroups,
            )

            disable_sids: list[tuple[Any, int]] = []
            restricting_sids: list[tuple[Any, int]] = [(user_sid, 0)]
            for sid, attributes in source_groups:
                sid_text = win32security.ConvertSidToStringSid(sid)
                if sid_text in _ADMINISTRATIVE_SIDS:
                    disable_sids.append((sid, 0))
                if (
                    attributes & win32security.SE_GROUP_ENABLED
                    and not attributes & win32security.SE_GROUP_USE_FOR_DENY_ONLY
                    and sid_text not in _ADMINISTRATIVE_SIDS
                ):
                    restricting_sids.append((sid, 0))

            restricting_sids = self._deduplicate_sid_attributes(restricting_sids)
            restricted_token = win32security.CreateRestrictedToken(
                source_token,
                DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
                disable_sids,
                [],
                restricting_sids,
            )
            self._verify_restricted_token(restricted_token)
            self._close_restricted_token()
            self._restricted_token = restricted_token
            restricted_token = None

            logger.info(
                "Restricted runner token created and verified "
                "(disabled_admin_sids=%d, restricting_sids=%d)",
                len(disable_sids),
                len(restricting_sids),
            )
            return True

        except SandboxUnavailable:
            raise
        except Exception as exc:
            raise SandboxUnavailable(
                f"restricted token initialization failed: {exc}"
            ) from exc
        finally:
            if source_token is not None:
                source_token.Close()
            if restricted_token is not None:
                restricted_token.Close()

    @staticmethod
    def _deduplicate_sid_attributes(
        values: list[tuple[Any, int]],
    ) -> list[tuple[Any, int]]:
        import win32security

        result: list[tuple[Any, int]] = []
        seen: set[str] = set()
        for sid, attributes in values:
            sid_text = win32security.ConvertSidToStringSid(sid)
            if sid_text not in seen:
                seen.add(sid_text)
                result.append((sid, attributes))
        return result

    @staticmethod
    def _verify_restricted_token(token: Any) -> None:
        import win32security

        if not win32security.IsTokenRestricted(token):
            raise SandboxUnavailable("CreateRestrictedToken returned an unrestricted token")
        if win32security.GetTokenInformation(token, win32security.TokenType) != 1:
            raise SandboxUnavailable("restricted runner token is not a primary token")

        privileges = win32security.GetTokenInformation(
            token,
            win32security.TokenPrivileges,
        )
        remaining_privileges = {
            win32security.LookupPrivilegeName(None, luid)
            for luid, _attributes in privileges
        }
        if remaining_privileges - {"SeChangeNotifyPrivilege"}:
            names = ", ".join(sorted(remaining_privileges))
            raise SandboxUnavailable(
                f"restricted runner token retained unexpected privileges: {names}"
            )

        groups = win32security.GetTokenInformation(token, win32security.TokenGroups)
        group_attributes = {
            win32security.ConvertSidToStringSid(sid): attributes
            for sid, attributes in groups
        }
        for sid_text in _ADMINISTRATIVE_SIDS & group_attributes.keys():
            if not group_attributes[sid_text] & win32security.SE_GROUP_USE_FOR_DENY_ONLY:
                raise SandboxUnavailable(
                    f"administrative SID remains enabled on runner token: {sid_text}"
                )

    @staticmethod
    def _hresult_hex(value: int) -> str:
        return f"0x{value & 0xFFFFFFFF:08X}"

    @staticmethod
    def _profile_apis() -> tuple[ctypes.WinDLL, ctypes.WinDLL, ctypes.WinDLL]:
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        userenv.CreateAppContainerProfile.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPVOID),
        ]
        userenv.CreateAppContainerProfile.restype = ctypes.c_long
        userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.LPVOID),
        ]
        userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
        userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
        userenv.DeleteAppContainerProfile.restype = ctypes.c_long
        advapi32.ConvertSidToStringSidW.argtypes = [
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        advapi32.FreeSid.argtypes = [wintypes.LPVOID]
        advapi32.FreeSid.restype = wintypes.LPVOID
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        return userenv, advapi32, kernel32

    @staticmethod
    def _sid_pointer_to_string(
        sid_pointer: int,
        advapi32: ctypes.WinDLL,
        kernel32: ctypes.WinDLL,
    ) -> str:
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            wintypes.LPVOID(sid_pointer),
            ctypes.byref(text),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            value = text.value
            if not value:
                raise SandboxUnavailable("AppContainer SID string is empty")
            return value
        finally:
            kernel32.LocalFree(text)

    def _create_appcontainer_profile(self) -> bool:
        """Create a private zero-capability AppContainer profile."""

        self._require_windows()
        if self._appcontainer_sid_ptr or self._appcontainer_profile_name:
            raise SandboxUnavailable("AppContainer profile state is already allocated")
        profile_name = f"ZCode.P39.{uuid.uuid4().hex}"
        sid = wintypes.LPVOID()
        userenv, advapi32, kernel32 = self._profile_apis()
        hr = int(
            userenv.CreateAppContainerProfile(
                profile_name,
                profile_name,
                "ZCode P3.9 isolated runner",
                None,
                0,
                ctypes.byref(sid),
            )
        )
        created = (hr & 0xFFFFFFFF) != HRESULT_ALREADY_EXISTS
        if not created:
            hr = int(
                userenv.DeriveAppContainerSidFromAppContainerName(
                    profile_name,
                    ctypes.byref(sid),
                )
            )
        if hr < 0 or not sid.value:
            raise SandboxUnavailable(
                "AppContainer profile initialization failed "
                f"(hresult={self._hresult_hex(hr)})"
            )
        try:
            sid_text = self._sid_pointer_to_string(
                int(sid.value),
                advapi32,
                kernel32,
            )
        except Exception:
            advapi32.FreeSid(sid)
            if created:
                userenv.DeleteAppContainerProfile(profile_name)
            raise

        self._appcontainer_profile_name = profile_name
        self._appcontainer_sid_ptr = int(sid.value)
        self._appcontainer_sid_text = sid_text
        self._profile_created_by_broker = created
        logger.info("AppContainer profile initialized: %s", profile_name)
        return True

    def _release_appcontainer_profile(self) -> None:
        sid_pointer = self._appcontainer_sid_ptr
        profile_name = self._appcontainer_profile_name
        created = self._profile_created_by_broker
        # No native AppContainer resources were ever created: nothing to
        # release, and no need to load the Win32 API set (keeps the broker
        # importable/closable on non-Windows CI for contract tests).
        if not sid_pointer and not (profile_name and created):
            self._appcontainer_profile_name = None
            self._profile_created_by_broker = False
            return
        userenv, advapi32, _kernel32 = self._profile_apis()
        if sid_pointer:
            advapi32.FreeSid(wintypes.LPVOID(sid_pointer))
            self._appcontainer_sid_ptr = 0
            self._appcontainer_sid_text = None
        if profile_name and created:
            hr = int(userenv.DeleteAppContainerProfile(profile_name))
            if hr < 0:
                raise SandboxUnavailable(
                    "DeleteAppContainerProfile failed "
                    f"(hresult={self._hresult_hex(hr)})"
                )
        self._appcontainer_profile_name = None
        self._profile_created_by_broker = False

    @property
    def appcontainer_sid_pointer(self) -> int:
        """Return the SID pointer owned by the initialized broker."""

        return self._appcontainer_sid_ptr

    @property
    def appcontainer_sid(self) -> str | None:
        return self._appcontainer_sid_text

    @property
    def restricted_token(self) -> Any | None:
        """Return the verified primary token for a restricted process launch."""

        return self._restricted_token

    def _close_restricted_token(self) -> None:
        token = self._restricted_token
        self._restricted_token = None
        if token is not None:
            token.Close()

    def close(self) -> None:
        """Release native handles owned by the isolation broker."""

        with self._state_lock:
            if self._closed:
                return
            self._accepting_launches = False
            if self._active_launches:
                raise SandboxUnavailable(
                    "cannot close isolation broker while child launches are active"
                )
            cleanup_errors = self._cleanup_native_state()
            if cleanup_errors:
                raise SandboxUnavailable(
                    "isolation cleanup failed: " + "; ".join(cleanup_errors)
                )
            if self._boundary is not None:
                self._boundary.initialization_verified = False
            self._boundary = None
            self._closed = True

    def acquire_launch(self) -> None:
        """Pin ACL/Profile state while a sandbox handle may launch children."""

        with self._state_lock:
            boundary = self._boundary
            if (
                not self._accepting_launches
                or boundary is None
                or not boundary.initialization_verified
            ):
                raise SandboxUnavailable("isolation broker is not accepting launches")
            self._active_launches += 1

    def release_launch(self) -> None:
        with self._state_lock:
            if self._active_launches <= 0:
                raise SandboxUnavailable("isolation launch reference underflow")
            self._active_launches -= 1

    def _validate_initialization_config(self) -> None:
        if self._path_is_reparse_point(self.config.workspace_root):
            raise SandboxUnavailable("workspace_root cannot be a reparse point")
        workspace = self._normalized_path(self.config.workspace_root)
        if not os.path.isdir(workspace):
            raise SandboxUnavailable(f"workspace_root does not exist: {workspace}")
        self._enumerate_acl_paths(workspace)
        if self.config.enable_workspace_acl and not self.config.enable_appcontainer:
            raise SandboxUnavailable(
                "workspace ACL requires AppContainer package SID isolation"
            )
        if self.config.enable_egress_filter and self.config.egress_allowlist:
            raise SandboxUnavailable(
                "non-empty egress_allowlist requires a WFP or proxy broker"
            )
        if not self.config.enable_egress_filter:
            raise SandboxUnavailable(
                "P3.9 AppContainer execution requires default-deny egress filtering"
            )

        deny_paths = tuple(self._normalized_path(path) for path in self.config.deny_paths)
        for deny_path in deny_paths:
            if self._paths_overlap(workspace, deny_path):
                raise SandboxUnavailable(f"deny_path overlaps workspace: {deny_path}")

        seen_runtime_roots: set[str] = set()
        for runtime_root in self.config.runtime_roots:
            if self._path_is_reparse_point(runtime_root):
                raise SandboxUnavailable("runtime_root cannot be a reparse point")
            normalized = self._normalized_path(runtime_root)
            if normalized in seen_runtime_roots:
                raise SandboxUnavailable(f"duplicate runtime_root: {normalized}")
            if not os.path.isdir(normalized):
                raise SandboxUnavailable(f"runtime_root does not exist: {normalized}")
            if self._paths_overlap(workspace, normalized):
                raise SandboxUnavailable(
                    f"runtime_root overlaps workspace: {normalized}"
                )
            for deny_path in deny_paths:
                if self._paths_overlap(normalized, deny_path):
                    raise SandboxUnavailable(
                        f"runtime_root overlaps deny_path: {normalized}"
                    )
            for existing_root in seen_runtime_roots:
                if self._paths_overlap(normalized, existing_root):
                    raise SandboxUnavailable(
                        f"runtime_roots overlap: {normalized} and {existing_root}"
                    )
            self._enumerate_acl_paths(normalized)
            seen_runtime_roots.add(normalized)

    def _rollback_initialization(self) -> list[str]:
        return self._cleanup_native_state()

    def _cleanup_native_state(self) -> list[str]:
        errors: list[str] = []
        cleanup_steps = (
            ("secret handle clearing", self._clear_secret_handles),
            ("runtime ACL restoration", self._restore_runtime_acls),
            ("workspace ACL restoration", self._restore_workspace_acl),
            ("AppContainer profile release", self._release_appcontainer_profile),
            ("restricted token close", self._close_restricted_token),
        )
        for label, cleanup in cleanup_steps:
            try:
                cleanup()
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        self._cleanup_pending = bool(errors)
        return errors

    def _clear_secret_handles(self) -> None:
        for handle in self._secret_handles.values():
            handle.clear()
        self._secret_handles.clear()

    @property
    def accepting_launches(self) -> bool:
        with self._state_lock:
            return self._accepting_launches and not self._cleanup_pending

    def _ensure_sandbox_temp_directory(self) -> str:
        temp_directory = os.path.join(
            self._normalized_path(self.config.workspace_root),
            ".tmp",
        )
        os.makedirs(temp_directory, exist_ok=True)
        return temp_directory

    def _ensure_sandbox_local_app_data(self) -> str:
        local_app_data = os.path.join(
            self._normalized_path(self.config.workspace_root),
            ".local",
        )
        os.makedirs(local_app_data, exist_ok=True)
        return local_app_data

    @staticmethod
    def _normalized_path(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    @staticmethod
    def _path_is_reparse_point(path: str) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return False
        attributes = getattr(info, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)

    @classmethod
    def _enumerate_acl_paths(cls, root: str) -> tuple[str, ...]:
        """Enumerate a tree without following reparse points."""

        root_path = os.path.normcase(os.path.abspath(root))
        if cls._path_is_reparse_point(root_path):
            raise SandboxUnavailable(f"reparse point is not allowed: {root_path}")

        paths = [root_path]
        pending = [root_path]
        while pending:
            current = pending.pop()
            try:
                entries = sorted(os.scandir(current), key=lambda entry: entry.name.lower())
            except OSError as exc:
                raise SandboxUnavailable(
                    f"cannot enumerate isolation path: {current}: {exc}"
                ) from exc
            for entry in entries:
                child = os.path.normcase(os.path.abspath(entry.path))
                if cls._path_is_reparse_point(child):
                    raise SandboxUnavailable(f"reparse point is not allowed: {child}")
                paths.append(child)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(child)
                except OSError as exc:
                    raise SandboxUnavailable(
                        f"cannot inspect isolation path: {child}: {exc}"
                    ) from exc
        return tuple(paths)

    @staticmethod
    def _paths_overlap(first: str, second: str) -> bool:
        try:
            return os.path.commonpath((first, second)) in (first, second)
        except ValueError:
            return False

    @staticmethod
    def _current_user_sid() -> Any:
        import win32api
        import win32security

        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            TOKEN_QUERY,
        )
        try:
            sid, _attributes = win32security.GetTokenInformation(
                token,
                win32security.TokenUser,
            )
            return sid
        finally:
            token.Close()

    @staticmethod
    def _snapshot_acl(path: str) -> _AclSnapshot:
        import win32security

        descriptor = win32security.GetNamedSecurityInfo(
            path,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        original_sddl = (
            win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
                descriptor,
                win32security.SDDL_REVISION_1,
                win32security.DACL_SECURITY_INFORMATION,
            )
        )
        control, _revision = descriptor.GetSecurityDescriptorControl()
        return _AclSnapshot(
            path=path,
            original_sddl=original_sddl,
            was_protected=bool(control & win32security.SE_DACL_PROTECTED),
            original_descriptor=descriptor,
        )

    def _restore_acl(self, snapshot: _AclSnapshot) -> None:
        import win32security

        original_descriptor = snapshot.original_descriptor
        original_dacl = original_descriptor.GetSecurityDescriptorDacl()
        expected_aces = self._dacl_ace_signature(original_dacl)
        win32security.SetFileSecurity(
            snapshot.path,
            win32security.DACL_SECURITY_INFORMATION,
            original_descriptor,
        )
        restored_descriptor = win32security.GetNamedSecurityInfo(
            snapshot.path,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        restored_control, _revision = restored_descriptor.GetSecurityDescriptorControl()
        restored_protected = bool(restored_control & win32security.SE_DACL_PROTECTED)
        restored_aces = self._dacl_ace_signature(
            restored_descriptor.GetSecurityDescriptorDacl()
        )
        if (
            restored_protected != snapshot.was_protected
            or restored_aces != expected_aces
        ):
            raise SandboxUnavailable(
                f"DACL restoration verification failed: {snapshot.path}"
            )

    def _restore_workspace_acl(self) -> None:
        snapshots = self._workspace_acl_snapshots
        if not snapshots:
            return
        errors: list[str] = []
        # Restore parents before unprotected descendants so Windows inheritance
        # is recalculated from the original parent DACL rather than the broker
        # ACE that was applied during initialization.
        ordered = sorted(
            snapshots.values(),
            key=lambda snapshot: snapshot.path.count(os.sep),
        )
        for snapshot in ordered:
            try:
                self._restore_acl(snapshot)
            except Exception as exc:
                errors.append(f"{snapshot.path}: {exc}")
            else:
                snapshots.pop(snapshot.path, None)
        if errors:
            raise SandboxUnavailable(
                "workspace DACL restoration failed: " + "; ".join(errors)
            )
        self._workspace_acl_snapshot = None

    def _restore_runtime_acls(self) -> None:
        errors: list[str] = []
        ordered = sorted(
            self._runtime_acl_snapshots.values(),
            key=lambda snapshot: snapshot.path.count(os.sep),
        )
        for snapshot in ordered:
            try:
                self._restore_acl(snapshot)
            except Exception as exc:
                errors.append(f"{snapshot.path}: {exc}")
            else:
                self._runtime_acl_snapshots.pop(snapshot.path, None)
        if errors:
            raise SandboxUnavailable("runtime DACL restoration failed: " + "; ".join(errors))

    @staticmethod
    def _dacl_ace_signature(dacl: Any | None) -> tuple[Any, ...] | None:
        if dacl is None:
            return None

        import win32security

        signature: list[tuple[int, int, int, str, tuple[Any, ...]]] = []
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            ace_type, ace_flags = ace[0]
            access_mask = ace[1]
            sid_text = win32security.ConvertSidToStringSid(ace[2])
            signature.append(
                (
                    ace_type,
                    ace_flags,
                    access_mask,
                    sid_text,
                    tuple(ace[3:]),
                )
            )
        return tuple(signature)

    @staticmethod
    def _verify_acl(
        path: str,
        required_aces: dict[str, int],
        *,
        require_protected: bool,
        require_inheritable: bool = True,
    ) -> None:
        import win32security

        descriptor = win32security.GetNamedSecurityInfo(
            path,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        control, _revision = descriptor.GetSecurityDescriptorControl()
        if require_protected and not control & win32security.SE_DACL_PROTECTED:
            raise SandboxUnavailable(f"DACL is not protected: {path}")

        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None:
            raise SandboxUnavailable(f"DACL is missing: {path}")

        inheritance = (
            win32security.OBJECT_INHERIT_ACE
            | win32security.CONTAINER_INHERIT_ACE
        )
        verified: dict[str, int] = {}
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            ace_type, ace_flags = ace[0]
            access_mask = ace[1]
            sid_text = win32security.ConvertSidToStringSid(ace[2])
            if (
                ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE
                and (
                    not require_inheritable
                    or ace_flags & inheritance == inheritance
                )
            ):
                verified[sid_text] = verified.get(sid_text, 0) | access_mask

        missing = {
            sid_text: required_mask
            for sid_text, required_mask in required_aces.items()
            if verified.get(sid_text, 0) & required_mask != required_mask
        }
        if missing:
            raise SandboxUnavailable(
                f"DACL missing required inheritable ACEs for {path}: "
                + ", ".join(sorted(missing))
            )

    @classmethod
    def _verify_workspace_acl(
        cls,
        workspace: str,
        required_aces: dict[str, int],
    ) -> None:
        cls._verify_acl(workspace, required_aces, require_protected=True)

    def _apply_workspace_acl(self) -> bool:
        """Apply workspace ACL to restrict file system access.

        Applies a protected DACL granting host administration rights to the
        current user, SYSTEM and Administrators, plus task data rights to the
        private AppContainer package SID.

        Returns True if successfully applied.
        Raises SandboxUnavailable on failure.
        """
        self._require_windows()

        workspace = self._normalized_path(self.config.workspace_root)
        if not os.path.isdir(workspace):
            raise SandboxUnavailable(
                f"workspace_root does not exist: {workspace}"
            )

        try:
            import ntsecuritycon
            import win32security

            if not self._appcontainer_sid_text:
                raise SandboxUnavailable("AppContainer package SID is unavailable")
            current_user_sid = self._current_user_sid()
            system_sid = win32security.CreateWellKnownSid(
                win32security.WinLocalSystemSid,
                None,
            )
            administrators_sid = win32security.CreateWellKnownSid(
                win32security.WinBuiltinAdministratorsSid,
                None,
            )
            host_sids = (
                current_user_sid,
                system_sid,
                administrators_sid,
            )
            package_sid = win32security.ConvertStringSidToSid(
                self._appcontainer_sid_text
            )
            inheritance = (
                win32security.OBJECT_INHERIT_ACE
                | win32security.CONTAINER_INHERIT_ACE
            )
            package_access = (
                ntsecuritycon.FILE_GENERIC_READ
                | ntsecuritycon.FILE_GENERIC_WRITE
                | ntsecuritycon.FILE_GENERIC_EXECUTE
                | ntsecuritycon.DELETE
            )

            paths = self._enumerate_acl_paths(workspace)
            for path in paths:
                self._workspace_acl_snapshots[path] = self._snapshot_acl(path)

            for path in paths:
                if path == workspace:
                    dacl = win32security.ACL()
                    for sid in host_sids:
                        dacl.AddAccessAllowedAceEx(
                            win32security.ACL_REVISION_DS,
                            inheritance,
                            ntsecuritycon.FILE_ALL_ACCESS,
                            sid,
                        )
                    dacl.AddAccessAllowedAceEx(
                        win32security.ACL_REVISION_DS,
                        inheritance,
                        package_access,
                        package_sid,
                    )
                    security_information = (
                        win32security.DACL_SECURITY_INFORMATION
                        | win32security.PROTECTED_DACL_SECURITY_INFORMATION
                    )
                    required_aces = {
                        win32security.ConvertSidToStringSid(sid): ntsecuritycon.FILE_ALL_ACCESS
                        for sid in host_sids
                    }
                    required_aces[self._appcontainer_sid_text] = package_access
                    require_inheritable = True
                else:
                    descriptor = win32security.GetNamedSecurityInfo(
                        path,
                        win32security.SE_FILE_OBJECT,
                        win32security.DACL_SECURITY_INFORMATION,
                    )
                    dacl = descriptor.GetSecurityDescriptorDacl()
                    if dacl is None:
                        raise SandboxUnavailable(f"child path has a NULL DACL: {path}")
                    dacl.AddAccessAllowedAceEx(
                        win32security.ACL_REVISION_DS,
                        inheritance if os.path.isdir(path) else 0,
                        package_access,
                        package_sid,
                    )
                    security_information = win32security.DACL_SECURITY_INFORMATION
                    required_aces = {self._appcontainer_sid_text: package_access}
                    require_inheritable = os.path.isdir(path)
                win32security.SetNamedSecurityInfo(
                    path,
                    win32security.SE_FILE_OBJECT,
                    security_information,
                    None,
                    None,
                    dacl,
                    None,
                )
                self._verify_acl(
                    path,
                    required_aces,
                    require_protected=(path == workspace),
                    require_inheritable=require_inheritable,
                )
            self._workspace_acl_snapshot = self._workspace_acl_snapshots[workspace]
            # Keep the public/root verification seam explicit; callers and
            # rollback tests use it to inject a post-ACL failure.
            self._verify_workspace_acl(workspace, {
                win32security.ConvertSidToStringSid(sid): ntsecuritycon.FILE_ALL_ACCESS
                for sid in host_sids
            } | {self._appcontainer_sid_text: package_access})

            test_file = os.path.join(workspace, ".isolation-test")
            try:
                with open(test_file, "w", encoding="utf-8") as stream:
                    stream.write("test")
                os.remove(test_file)
            except OSError as exc:
                raise SandboxUnavailable(
                    f"workspace not writable after DACL application: {workspace}: {exc}"
                ) from exc

            logger.info(
                "Workspace DACL applied and verified: %s (deny=%d paths)",
                workspace, len(self.config.deny_paths),
            )
            return True

        except SandboxUnavailable:
            raise
        except Exception as exc:
            raise SandboxUnavailable(
                f"workspace ACL initialization failed: {exc}"
            ) from exc

    def _apply_runtime_acls(self) -> bool:
        """Grant the package SID inheritable read/execute access to runtimes."""

        self._require_windows()
        if not self._appcontainer_sid_text:
            raise SandboxUnavailable("AppContainer package SID is unavailable")

        try:
            import ntsecuritycon
            import win32security

            package_sid = win32security.ConvertStringSidToSid(
                self._appcontainer_sid_text
            )
            inheritance = (
                win32security.OBJECT_INHERIT_ACE
                | win32security.CONTAINER_INHERIT_ACE
            )
            runtime_access = (
                ntsecuritycon.FILE_GENERIC_READ
                | ntsecuritycon.FILE_GENERIC_EXECUTE
            )
            runtime_paths: list[str] = []
            for configured_root in self.config.runtime_roots:
                runtime_root = self._normalized_path(configured_root)
                runtime_paths.extend(self._enumerate_acl_paths(runtime_root))

            for path in runtime_paths:
                self._runtime_acl_snapshots[path] = self._snapshot_acl(path)

            for path in runtime_paths:
                descriptor = win32security.GetNamedSecurityInfo(
                    path,
                    win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION,
                )
                dacl = descriptor.GetSecurityDescriptorDacl()
                if dacl is None:
                    raise SandboxUnavailable(f"runtime path has a NULL DACL: {path}")
                dacl.AddAccessAllowedAceEx(
                    win32security.ACL_REVISION_DS,
                    inheritance if os.path.isdir(path) else 0,
                    runtime_access,
                    package_sid,
                )
                win32security.SetNamedSecurityInfo(
                    path,
                    win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    dacl,
                    None,
                )
                self._verify_acl(
                    path,
                    {self._appcontainer_sid_text: runtime_access},
                    require_protected=False,
                    require_inheritable=os.path.isdir(path),
                )
            return True
        except SandboxUnavailable:
            raise
        except Exception as exc:
            raise SandboxUnavailable(
                f"runtime ACL initialization failed: {exc}"
            ) from exc

    @staticmethod
    def _validate_environment_entry(key: str, value: str) -> None:
        if not key or "=" in key or "\x00" in key:
            raise SandboxUnavailable(f"invalid environment variable name: {key!r}")
        if "\x00" in value:
            raise SandboxUnavailable(
                f"environment variable contains NUL: {key!r}"
            )
        key_upper = key.upper()
        if any(block in key_upper for block in SECRET_ENV_BLOCKLIST):
            raise SandboxUnavailable(
                f"environment variable looks like a secret: {key}"
            )

    def filter_environment(
        self, extra_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build a minimal environment for the sandboxed process.

        Only whitelisted variables from os.environ are included.
        Extra env from the tool/task is merged on top.
        Any variable whose key (case-insensitive) matches SECRET_ENV_BLOCKLIST
        is rejected.
        """
        result: dict[str, str] = {}
        host_environment = {key.upper(): value for key, value in os.environ.items()}
        whitelist = {key.upper() for key in self.config.env_whitelist}

        # Whitelist from host environment
        for key in sorted(whitelist):
            value = host_environment.get(key)
            if value is not None:
                self._validate_environment_entry(key, value)
                result[key] = value

        # Merge extra environment
        if extra_env:
            for key, value in extra_env.items():
                if not isinstance(key, str):
                    raise SandboxUnavailable("environment variable names must be strings")
                if not isinstance(value, str):
                    raise SandboxUnavailable("environment variable values must be strings")
                self._validate_environment_entry(key, value)
                result[key.upper()] = value

        if (
            self.config.enable_appcontainer
            and self._boundary is not None
            and self._boundary.initialization_verified
        ):
            temp_directory = self._ensure_sandbox_temp_directory()
            result["TEMP"] = temp_directory
            result["TMP"] = temp_directory
            result["LOCALAPPDATA"] = self._ensure_sandbox_local_app_data()

        if self._boundary is not None:
            self._boundary.env_vars_blocked = sum(
                1 for key in os.environ if key.upper() not in whitelist
            )

        return result

    def issue_secret(
        self,
        handle_id: str,
        tool_name: str,
        task_id: str,
        value: str,
        lifetime_sec: int | None = None,
    ) -> SecretHandle:
        """Issue a one-time secret handle bound to a specific tool+task.

        The actual value is never written to environment, args, or logs.
        The handle must be consumed exactly once before the lifetime expires.
        """
        effective_lifetime = (
            self.config.max_secret_lifetime_sec
            if lifetime_sec is None
            else lifetime_sec
        )
        if effective_lifetime <= 0:
            raise SandboxUnavailable("secret handle lifetime must be positive")
        if effective_lifetime > self.config.max_secret_lifetime_sec:
            raise SandboxUnavailable(
                "secret handle lifetime exceeds configured maximum"
            )

        with self._state_lock:
            if self._closed or self._cleanup_pending:
                raise SandboxUnavailable("isolation broker is not available")
            if handle_id in self._secret_handles:
                raise SandboxUnavailable(
                    f"secret handle already exists: {handle_id}"
                )

            created_at = time.monotonic()
            handle = SecretHandle(
                handle_id=handle_id,
                tool_name=tool_name,
                task_id=task_id,
                created_at=created_at,
                expires_at=created_at + effective_lifetime,
                _value=value,
            )

            if self._boundary is not None:
                self._boundary.secrets_issued.append(handle_id)

            self._secret_handles[handle_id] = handle
        logger.info(
            "Secret handle issued: %s for tool=%s task=%s (lifetime=%ds)",
            handle_id, tool_name, task_id, effective_lifetime,
        )
        return handle

    def consume_secret(self, handle_id: str, tool_name: str, task_id: str) -> str:
        """Consume a secret handle — verifies tool+task binding."""
        with self._state_lock:
            if self._closed or self._cleanup_pending:
                raise SandboxUnavailable("isolation broker is not available")
            handle = self._secret_handles.get(handle_id)
            if handle is None:
                raise SandboxUnavailable(f"secret handle not found: {handle_id}")

            if handle.tool_name != tool_name or handle.task_id != task_id:
                raise SandboxUnavailable(
                    f"secret handle {handle_id} not bound to "
                    f"tool={tool_name} task={task_id}"
                )

            return handle.consume()

    def check_egress(self, host: str, port: int) -> EgressRule | None:
        """Check if a network egress destination is allowed.

        Returns the matching EgressRule if allowed, None if denied.
        Default-deny: if no rules match, egress is blocked.
        """
        if not self.config.enable_egress_filter:
            return EgressRule(
                host=host, port=port, reason="egress filter disabled",
            )

        for rule in self._boundary.egress_rules if self._boundary else ():
            if rule.host == host and rule.port == port:
                return rule
            # Wildcard host match
            if rule.host == "*" and rule.port == port:
                return rule

        # Check config allowlist
        for allowed in self.config.egress_allowlist:
            parts = allowed.rsplit(":", 1)
            if len(parts) == 2:
                allowed_host, allowed_port = parts
                try:
                    if (allowed_host == "*" or allowed_host == host) and int(allowed_port) == port:
                        return EgressRule(
                            host=host, port=port,
                            reason=f"allowed by config: {allowed}",
                        )
                except ValueError:
                    continue

        logger.warning("Egress denied (default-deny): %s:%d", host, port)
        return None

    @property
    def boundary(self) -> IsolationBoundary | None:
        """The current isolation boundary, or None if not initialized."""
        return self._boundary

    @property
    def workspace_root(self) -> str:
        return self._normalized_path(self.config.workspace_root)

    @property
    def runtime_roots(self) -> tuple[str, ...]:
        return tuple(
            self._normalized_path(path) for path in self.config.runtime_roots
        )

    def path_is_in_workspace(self, path: str) -> bool:
        normalized = self._normalized_path(path)
        try:
            return (
                os.path.commonpath((self.workspace_root, normalized))
                == self.workspace_root
            )
        except ValueError:
            return False

    def executable_is_authorized(self, executable: str) -> bool:
        normalized = self._normalized_path(executable)
        if self.path_is_in_workspace(normalized):
            return True
        for runtime_root in self.runtime_roots:
            try:
                if os.path.commonpath((runtime_root, normalized)) == runtime_root:
                    return True
            except ValueError:
                continue
        return False


def create_default_isolation(
    workspace_root: str,
    *,
    runtime_roots: tuple[str, ...] = (),
    deny_paths: tuple[str, ...] = (),
    egress_allowlist: tuple[str, ...] = (),
) -> WindowsIsolationBroker:
    """Create a default isolation broker for a task workspace.

    Args:
        workspace_root: The task's workspace directory.
        runtime_roots: Explicit trusted runtime directories granted read/execute.
        deny_paths: Paths that must be inaccessible (Control DB, source, etc.)
        egress_allowlist: Allowed network destinations (host:port format).

    Returns:
        An uninitialized WindowsIsolationBroker. Call initialize() before use.
    """
    config = IsolationConfig(
        workspace_root=workspace_root,
        runtime_roots=runtime_roots,
        deny_paths=deny_paths,
        egress_allowlist=egress_allowlist,
    )
    return WindowsIsolationBroker(config)


__all__ = [
    "DEFAULT_ENV_WHITELIST",
    "SECRET_ENV_BLOCKLIST",
    "EgressRule",
    "IsolationBoundary",
    "IsolationConfig",
    "SecretHandle",
    "WindowsIsolationBroker",
    "create_default_isolation",
]
