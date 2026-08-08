"""Windows Credential Manager backed implementation of ``SecretStore``."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Any

from packages.platform.shared.contracts import SecretRef, SecretStore
from packages.platform.shared.errors import SecretAccessError

from ._errors import UnsupportedPlatformError

logger = logging.getLogger(__name__)

CRED_PREFIX = "Zcode/"
ERROR_NOT_FOUND = 1168
MAX_CREDENTIAL_BLOB_SIZE = 512


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _error_code(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    args = getattr(exc, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


class WindowsCredentialStore(SecretStore):
    """Store binary secret blobs in the current user's Credential Manager."""

    def __init__(self, *, persist: int | None = None) -> None:
        self._persist = persist

    @staticmethod
    def is_supported() -> bool:
        if sys.platform != "win32":
            return False
        try:
            api = ctypes.WinDLL("advapi32", use_last_error=True)
            return all(
                hasattr(api, name)
                for name in ("CredWriteW", "CredReadW", "CredDeleteW")
            )
        except (AttributeError, OSError):
            return False

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Credential Manager requires Windows")
        if not self.is_supported():
            raise UnsupportedPlatformError("Credential Manager API is unavailable")

    @staticmethod
    def _validate_ref(ref: SecretRef) -> None:
        if not isinstance(ref, SecretRef):
            raise TypeError("ref must be a SecretRef")
        target = f"{CRED_PREFIX}{ref.key_id}"
        if len(target) >= 512 or "\x00" in target:
            raise ValueError("credential target name is too long")

    def _target(self, ref: SecretRef) -> str:
        self._validate_ref(ref)
        return f"{CRED_PREFIX}{ref.key_id}"

    @staticmethod
    def _api() -> Any:
        api = ctypes.WinDLL("advapi32", use_last_error=True)
        credential_ptr = ctypes.POINTER(_CREDENTIALW)
        api.CredWriteW.argtypes = [credential_ptr, wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(credential_ptr),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredEnumerateW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(credential_ptr),
        ]
        api.CredEnumerateW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    @staticmethod
    def _raise(operation: str, exc: BaseException) -> SecretAccessError:
        # Do not include target names or provider error text in the exception.
        code = _error_code(exc)
        suffix = f" (winerror={code})" if code is not None else ""
        return SecretAccessError(f"Credential Manager {operation} failed{suffix}")

    @classmethod
    def _api_checked(cls) -> Any:
        try:
            return cls._api()
        except Exception as exc:
            raise cls._raise("initialization", exc) from exc

    def _credential(self, ref: SecretRef, plaintext: bytes) -> tuple[_CREDENTIALW, Any]:
        if not isinstance(plaintext, bytes):
            raise TypeError("plaintext must be bytes")
        if len(plaintext) > MAX_CREDENTIAL_BLOB_SIZE:
            raise ValueError(
                f"Credential Manager generic blobs are limited to {MAX_CREDENTIAL_BLOB_SIZE} bytes"
            )
        backing = ctypes.create_string_buffer(plaintext) if plaintext else None
        credential = _CREDENTIALW(
            Flags=0,
            Type=1,  # CRED_TYPE_GENERIC
            TargetName=self._target(ref),
            Comment=None,
            LastWritten=wintypes.FILETIME(),
            CredentialBlobSize=len(plaintext),
            CredentialBlob=(
                ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte))
                if backing is not None
                else None
            ),
            Persist=2 if self._persist is None else self._persist,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName=ref.label or "",
        )
        return credential, backing

    async def store(self, ref: SecretRef, plaintext: bytes) -> None:
        self._require_windows()
        api = self._api_checked()
        credential, _backing = self._credential(ref, plaintext)
        try:
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception as exc:
            raise self._raise("write", exc) from exc
        logger.info("Stored Credential Manager item for key_id=%s", ref.key_id)

    async def load(self, ref: SecretRef) -> bytes:
        self._require_windows()
        try:
            api = self._api()
            ptr = ctypes.POINTER(_CREDENTIALW)()
            if not api.CredReadW(self._target(ref), 1, 0, ctypes.byref(ptr)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                credential = ptr.contents
                size = int(credential.CredentialBlobSize)
                if size > MAX_CREDENTIAL_BLOB_SIZE:
                    raise SecretAccessError("Credential Manager returned an invalid blob size")
                if size == 0:
                    return b""
                if not credential.CredentialBlob:
                    raise SecretAccessError("Credential Manager returned a missing blob")
                return ctypes.string_at(credential.CredentialBlob, size)
            finally:
                api.CredFree(ptr)
        except SecretAccessError:
            raise
        except Exception as exc:
            raise self._raise("read", exc) from exc

    async def delete(self, ref: SecretRef) -> bool:
        self._require_windows()
        try:
            api = self._api()
            if not api.CredDeleteW(self._target(ref), 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            return True
        except Exception as exc:
            if _error_code(exc) == ERROR_NOT_FOUND:
                return False
            raise self._raise("delete", exc) from exc

    async def list_refs(self) -> list[SecretRef]:
        self._require_windows()
        api = self._api_checked()
        count = wintypes.DWORD()
        ptr_array = ctypes.POINTER(_CREDENTIALW)()
        try:
            if not api.CredEnumerateW(
                f"{CRED_PREFIX}*", 0, ctypes.byref(count), ctypes.byref(ptr_array)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception as exc:
            if _error_code(exc) == ERROR_NOT_FOUND:
                return []
            raise self._raise("enumerate", exc) from exc

        refs: list[SecretRef] = []
        try:
            pointers = ctypes.cast(
                ptr_array,
                ctypes.POINTER(ctypes.POINTER(_CREDENTIALW) * count.value),
            ).contents
            for item in pointers:
                credential = item.contents
                target = credential.TargetName or ""
                if not target.startswith(CRED_PREFIX):
                    continue
                key_id = target[len(CRED_PREFIX) :]
                if key_id:
                    refs.append(SecretRef(key_id=key_id, label=credential.UserName or ""))
        finally:
            if ptr_array:
                api.CredFree(ptr_array)
        refs.sort(key=lambda ref: ref.key_id)
        return refs

    async def rotate(self, ref: SecretRef, new_plaintext: bytes) -> None:
        # CredWriteW is an upsert, avoiding a delete-before-write gap.
        await self.store(ref, new_plaintext)
        logger.info("Rotated Credential Manager item for key_id=%s", ref.key_id)


__all__ = ["CRED_PREFIX", "MAX_CREDENTIAL_BLOB_SIZE", "WindowsCredentialStore"]
