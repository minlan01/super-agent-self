"""Disposable Windows AppContainer launch probe for P3.9.

This script deliberately lives under artifacts, not the production package. It
creates a unique AppContainer profile, grants that package SID access only to
a temporary probe workspace, starts a child through SECURITY_CAPABILITIES,
records containment/file/network observations, and removes the profile/files.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
from ctypes import wintypes
from pathlib import Path

import ntsecuritycon
import win32security

HRESULT = ctypes.c_long
SIZE_T = ctypes.c_size_t
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INFINITE = 0xFFFFFFFF
ERROR_ALREADY_EXISTS = 183
TOKEN_QUERY = 0x0008
TOKEN_IS_APPCONTAINER = 29
TOKEN_INTEGRITY_LEVEL = 25
TOKEN_APPCONTAINER_SID = 31


class SID_AND_ATTRIBUTES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class SECURITY_ATTRIBUTES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", wintypes.LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)

userenv.CreateAppContainerProfile.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.POINTER(SID_AND_ATTRIBUTES),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.LPVOID),
]
userenv.CreateAppContainerProfile.restype = HRESULT
userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(wintypes.LPVOID),
]
userenv.DeriveAppContainerSidFromAppContainerName.restype = HRESULT
userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
userenv.DeleteAppContainerProfile.restype = HRESULT

advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
advapi32.CreateProcessAsUserW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.BOOL,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
advapi32.CreateProcessAsUserW.restype = wintypes.BOOL
advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL
advapi32.IsTokenRestricted.argtypes = [wintypes.HANDLE]
advapi32.IsTokenRestricted.restype = wintypes.BOOL

kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.BOOL,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.InitializeProcThreadAttributeList.argtypes = [
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(SIZE_T),
]
kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
kernel32.UpdateProcThreadAttribute.argtypes = [
    wintypes.LPVOID,
    wintypes.DWORD,
    SIZE_T,
    wintypes.LPVOID,
    SIZE_T,
    wintypes.LPVOID,
    ctypes.POINTER(SIZE_T),
]
kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
kernel32.DeleteProcThreadAttributeList.restype = None
kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.DWORD,
]
kernel32.CreatePipe.restype = wintypes.BOOL
kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
kernel32.SetHandleInformation.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
kernel32.LocalFree.restype = wintypes.HLOCAL
advapi32.FreeSid.argtypes = [wintypes.LPVOID]
advapi32.FreeSid.restype = wintypes.LPVOID


def hex_hresult(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08X}"


def check_bool(ok: object, operation: str) -> None:
    if not ok:
        code = ctypes.get_last_error()
        raise OSError(code, f"{operation} failed", None, code)


def sid_to_string(sid: wintypes.LPVOID) -> str:
    text = wintypes.LPWSTR()
    check_bool(advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)), "ConvertSidToStringSidW")
    try:
        return text.value
    finally:
        kernel32.LocalFree(text)


def create_profile(name: str) -> tuple[wintypes.LPVOID, dict[str, object]]:
    sid = wintypes.LPVOID()
    hr = int(
        userenv.CreateAppContainerProfile(
            name,
            name,
            "P3.9 disposable probe",
            None,
            0,
            ctypes.byref(sid),
        )
    )
    info: dict[str, object] = {"create_hresult": hex_hresult(hr)}
    if (hr & 0xFFFFFFFF) == (0x80070000 | ERROR_ALREADY_EXISTS):
        hr = int(userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid)))
        info["derive_hresult"] = hex_hresult(hr)
    if hr < 0:
        raise RuntimeError(f"profile SID creation failed: {hex_hresult(hr)}")
    info["sid"] = sid_to_string(sid)
    return sid, info


def grant_workspace(path: Path, package_sid_text: str) -> None:
    import win32api

    package_sid = win32security.ConvertStringSidToSid(package_sid_text)
    process_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32security.TOKEN_QUERY,
    )
    try:
        user_sid, _attributes = win32security.GetTokenInformation(
            process_token,
            win32security.TokenUser,
        )
    finally:
        process_token.Close()

    workspace_paths = [path, *sorted(path.rglob("*"), key=lambda item: len(item.parts))]
    for workspace_path in workspace_paths:
        sd = win32security.GetNamedSecurityInfo(
            str(workspace_path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        dacl = sd.GetSecurityDescriptorDacl()
        if dacl is None:
            dacl = win32security.ACL()
        flags = 0
        if workspace_path.is_dir():
            flags = (
                win32security.OBJECT_INHERIT_ACE
                | win32security.CONTAINER_INHERIT_ACE
            )
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            flags,
            ntsecuritycon.FILE_ALL_ACCESS,
            user_sid,
        )
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            flags,
            ntsecuritycon.FILE_GENERIC_READ
            | ntsecuritycon.FILE_GENERIC_WRITE
            | ntsecuritycon.FILE_GENERIC_EXECUTE
            | ntsecuritycon.DELETE,
            package_sid,
        )
        win32security.SetNamedSecurityInfo(
            str(workspace_path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )


def make_pipe() -> tuple[int, int]:
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    read = wintypes.HANDLE()
    write = wintypes.HANDLE()
    check_bool(
        kernel32.CreatePipe(
            ctypes.byref(read), ctypes.byref(write), ctypes.byref(sa), 0
        ),
        "CreatePipe",
    )
    check_bool(kernel32.SetHandleInformation(read, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation")
    return int(read.value), int(write.value)


def make_attribute_list(
    security: SECURITY_CAPABILITIES, inherited_handles: tuple[int, ...]
) -> tuple[ctypes.Array[ctypes.c_char], ctypes.Array[wintypes.HANDLE]]:
    size = SIZE_T()
    ctypes.set_last_error(0)
    kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    if not size.value:
        check_bool(False, "InitializeProcThreadAttributeList(size)")
    buffer = ctypes.create_string_buffer(size.value)
    check_bool(
        kernel32.InitializeProcThreadAttributeList(
            ctypes.cast(buffer, wintypes.LPVOID), 2, 0, ctypes.byref(size)
        ),
        "InitializeProcThreadAttributeList",
    )
    check_bool(
        kernel32.UpdateProcThreadAttribute(
            ctypes.cast(buffer, wintypes.LPVOID),
            0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.cast(ctypes.byref(security), wintypes.LPVOID),
            ctypes.sizeof(security),
            None,
            None,
        ),
        "UpdateProcThreadAttribute(security capabilities)",
    )
    handle_array_type = wintypes.HANDLE * len(inherited_handles)
    handle_array = handle_array_type(*(wintypes.HANDLE(value) for value in inherited_handles))
    check_bool(
        kernel32.UpdateProcThreadAttribute(
            ctypes.cast(buffer, wintypes.LPVOID),
            0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(handle_array, wintypes.LPVOID),
            ctypes.sizeof(handle_array),
            None,
            None,
        ),
        "UpdateProcThreadAttribute(handle list)",
    )
    return buffer, handle_array


def collect_pipe(handle: int, sink: list[bytes]) -> None:
    import msvcrt

    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb", buffering=0) as stream:
        sink.append(stream.read())


def query_process_token(process_handle: wintypes.HANDLE) -> dict[str, object]:
    token = wintypes.HANDLE()
    check_bool(
        advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)),
        "OpenProcessToken(child)",
    )
    try:
        is_appcontainer = wintypes.DWORD()
        returned = wintypes.DWORD()
        check_bool(
            advapi32.GetTokenInformation(
                token,
                TOKEN_IS_APPCONTAINER,
                ctypes.byref(is_appcontainer),
                ctypes.sizeof(is_appcontainer),
                ctypes.byref(returned),
            ),
            "GetTokenInformation(TokenIsAppContainer)",
        )
        size = wintypes.DWORD()
        ctypes.set_last_error(0)
        advapi32.GetTokenInformation(
            token,
            TOKEN_INTEGRITY_LEVEL,
            None,
            0,
            ctypes.byref(size),
        )
        integrity_sid = None
        if size.value:
            buffer = ctypes.create_string_buffer(size.value)
            check_bool(
                advapi32.GetTokenInformation(
                    token,
                    TOKEN_INTEGRITY_LEVEL,
                    buffer,
                    size,
                    ctypes.byref(size),
                ),
                "GetTokenInformation(TokenIntegrityLevel)",
            )
            label = ctypes.cast(buffer, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents
            integrity_sid = sid_to_string(label.Sid)
        appcontainer_size = wintypes.DWORD()
        ctypes.set_last_error(0)
        advapi32.GetTokenInformation(
            token,
            TOKEN_APPCONTAINER_SID,
            None,
            0,
            ctypes.byref(appcontainer_size),
        )
        appcontainer_sid = None
        if appcontainer_size.value:
            appcontainer_buffer = ctypes.create_string_buffer(appcontainer_size.value)
            check_bool(
                advapi32.GetTokenInformation(
                    token,
                    TOKEN_APPCONTAINER_SID,
                    appcontainer_buffer,
                    appcontainer_size,
                    ctypes.byref(appcontainer_size),
                ),
                "GetTokenInformation(TokenAppContainerSid)",
            )
            sid_pointer = ctypes.cast(
                appcontainer_buffer, ctypes.POINTER(wintypes.LPVOID)
            ).contents.value
            if sid_pointer:
                appcontainer_sid = sid_to_string(wintypes.LPVOID(sid_pointer))
        return {
            "is_appcontainer": bool(is_appcontainer.value),
            "is_restricted": bool(advapi32.IsTokenRestricted(token)),
            "integrity_sid": integrity_sid,
            "appcontainer_sid": appcontainer_sid,
        }
    finally:
        kernel32.CloseHandle(token)


def launch(
    api_name: str,
    sid: wintypes.LPVOID,
    executable: str,
    args: list[str],
    cwd: Path,
    restricted_token: object | None = None,
) -> dict[str, object]:
    stdout_read, stdout_write = make_pipe()
    stderr_read, stderr_write = make_pipe()
    security = SECURITY_CAPABILITIES(sid, None, 0, 0)
    attributes = None
    pi = PROCESS_INFORMATION()
    out: list[bytes] = []
    err: list[bytes] = []
    try:
        attributes, _handle_array = make_attribute_list(security, (stdout_write, stderr_write))
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = None
        startup.StartupInfo.hStdOutput = wintypes.HANDLE(stdout_write)
        startup.StartupInfo.hStdError = wintypes.HANDLE(stderr_write)
        startup.lpAttributeList = ctypes.cast(attributes, wintypes.LPVOID)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([executable, *args]))
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT
        if api_name == "CreateProcessW":
            ok = kernel32.CreateProcessW(
                executable,
                command,
                None,
                None,
                True,
                flags,
                None,
                str(cwd),
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(pi),
            )
        elif api_name.startswith("CreateProcessAsUserW-"):
            owned_token = restricted_token is None
            token = restricted_token
            if token is None:
                token = win32security.OpenProcessToken(
                    __import__("win32api").GetCurrentProcess(),
                    win32security.TOKEN_QUERY
                    | win32security.TOKEN_DUPLICATE
                    | win32security.TOKEN_ASSIGN_PRIMARY,
                )
            try:
                ok = advapi32.CreateProcessAsUserW(
                    int(token),
                    executable,
                    command,
                    None,
                    None,
                    True,
                    flags,
                    None,
                    str(cwd),
                    ctypes.byref(startup.StartupInfo),
                    ctypes.byref(pi),
                )
            finally:
                if owned_token:
                    token.Close()
        else:
            raise ValueError(api_name)
        if not ok:
            code = ctypes.get_last_error()
            return {"api": api_name, "created": False, "winerror": code}
        token_observation = query_process_token(pi.hProcess)
        kernel32.CloseHandle(wintypes.HANDLE(stdout_write))
        stdout_write = 0
        kernel32.CloseHandle(wintypes.HANDLE(stderr_write))
        stderr_write = 0
        out_thread = threading.Thread(target=collect_pipe, args=(stdout_read, out))
        err_thread = threading.Thread(target=collect_pipe, args=(stderr_read, err))
        stdout_read = 0
        stderr_read = 0
        out_thread.start()
        err_thread.start()
        wait = kernel32.WaitForSingleObject(pi.hProcess, 30_000)
        if wait == WAIT_TIMEOUT:
            kernel32.TerminateProcess(pi.hProcess, 124)
            kernel32.WaitForSingleObject(pi.hProcess, 5_000)
        elif wait != WAIT_OBJECT_0:
            raise RuntimeError(f"WaitForSingleObject returned {wait}")
        out_thread.join(5)
        err_thread.join(5)
        code = wintypes.DWORD()
        check_bool(
            kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code)),
            "GetExitCodeProcess",
        )
        stdout_text = b"".join(out).decode("utf-8", errors="replace")
        stderr_text = b"".join(err).decode("utf-8", errors="replace")
        result: dict[str, object] = {
            "api": api_name,
            "created": True,
            "pid": int(pi.dwProcessId),
            "exit_code": int(code.value),
            "token": token_observation,
            "stdout": stdout_text,
            "stderr": stderr_text,
        }
        try:
            result["child"] = json.loads(stdout_text)
        except json.JSONDecodeError:
            pass
        return result
    finally:
        if attributes is not None:
            kernel32.DeleteProcThreadAttributeList(ctypes.cast(attributes, wintypes.LPVOID))
        owned_handles = (
            stdout_read,
            stdout_write,
            stderr_read,
            stderr_write,
            int(pi.hThread or 0),
            int(pi.hProcess or 0),
        )
        for handle in owned_handles:
            if handle:
                kernel32.CloseHandle(wintypes.HANDLE(handle))


def start_loopback_server() -> tuple[
    socket.socket, int, threading.Event, threading.Thread
]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(1)
    port = server.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                client, _address = server.accept()
                with client:
                    client.settimeout(2)
                    client.recv(1024)
                    client.sendall(b"ok")
            except TimeoutError:
                continue
            except OSError:
                break

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server, port, stop, thread


def verify_parent_loopback(port: int) -> bool:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        connection.sendall(b"parent-probe")
        return connection.recv(20) == b"ok"


def create_probe_restricted_token() -> object:
    import win32api

    source = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32security.TOKEN_QUERY
        | win32security.TOKEN_DUPLICATE
        | win32security.TOKEN_ASSIGN_PRIMARY,
    )
    try:
        user_sid, _attributes = win32security.GetTokenInformation(
            source, win32security.TokenUser
        )
        groups = win32security.GetTokenInformation(source, win32security.TokenGroups)
        admin_sids = {
            "S-1-5-114",
            "S-1-5-32-544",
            "S-1-5-32-547",
            "S-1-5-32-548",
            "S-1-5-32-549",
            "S-1-5-32-550",
            "S-1-5-32-551",
            "S-1-5-32-556",
        }
        disabled: list[tuple[object, int]] = []
        restricting: list[tuple[object, int]] = [(user_sid, 0)]
        seen = {win32security.ConvertSidToStringSid(user_sid)}
        for group_sid, attributes in groups:
            text = win32security.ConvertSidToStringSid(group_sid)
            if text in admin_sids:
                disabled.append((group_sid, 0))
            if (
                attributes & win32security.SE_GROUP_ENABLED
                and not attributes & win32security.SE_GROUP_USE_FOR_DENY_ONLY
                and text not in admin_sids
                and text not in seen
            ):
                restricting.append((group_sid, 0))
                seen.add(text)
        return win32security.CreateRestrictedToken(
            source,
            0x1 | 0x4,
            disabled,
            [],
            restricting,
        )
    finally:
        source.Close()


def create_disposable_credential(target: str) -> dict[str, object]:
    import win32cred

    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": "p39-probe",
            "CredentialBlob": uuid.uuid4().hex,
            "Persist": win32cred.CRED_PERSIST_SESSION,
        },
        0,
    )
    stored = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
    return {
        "target": target,
        "created": True,
        "parent_visible": stored["TargetName"] == target,
    }


def delete_disposable_credential(target: str) -> dict[str, object]:
    import win32cred

    result: dict[str, object] = {}
    try:
        win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        result["delete_succeeded"] = True
    except Exception as exc:
        result["delete_succeeded"] = False
        result["delete_error"] = {
            "type": type(exc).__name__,
            "winerror": getattr(exc, "winerror", None),
        }
    try:
        win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        result["visible_after_delete"] = True
    except Exception:
        result["visible_after_delete"] = False
    return result


CHILD_SOURCE = r'''from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import socket
from ctypes import wintypes

workspace = Path(os.environ["P39_WORKSPACE"])
outside = Path(os.environ["P39_OUTSIDE"])
port = int(os.environ["P39_LOOPBACK_PORT"])
results = {}

class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]

def read_credential(target):
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [wintypes.LPVOID]
    advapi32.CredFree.restype = None
    credential = ctypes.POINTER(CREDENTIALW)()
    ok = advapi32.CredReadW(target, 1, 0, ctypes.byref(credential))
    if not ok:
        return {"ok": False, "winerror": ctypes.get_last_error()}
    try:
        return {"ok": True}
    finally:
        advapi32.CredFree(credential)

def failed(exc):
    return {
        "ok": False,
        "error": type(exc).__name__,
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
        "text": str(exc),
    }
for name, path in (
    ("workspace_read", workspace / "seed.txt"),
    ("outside_read", outside / "secret.txt"),
    ("user_profile_read", Path.home() / "NTUSER.DAT"),
):
    try:
        results[name] = {"ok": True, "value": path.read_bytes()[:80].decode(errors="replace")}
    except Exception as exc:
        results[name] = failed(exc)
results["credential_read"] = read_credential(
    os.environ["P39_CREDENTIAL_TARGET"]
)
try:
    target = workspace / "child-write.txt"
    target.write_text("appcontainer-write-ok", encoding="utf-8")
    results["workspace_write"] = {"ok": True, "value": target.read_text(encoding="utf-8")}
except Exception as exc:
    results["workspace_write"] = failed(exc)
try:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        connection.sendall(b"probe")
        results["loopback"] = {
            "ok": True,
            "value": connection.recv(20).decode(errors="replace"),
        }
except Exception as exc:
    results["loopback"] = failed(exc)
try:
    with socket.create_connection(("1.1.1.1", 80), timeout=3) as connection:
        results["internet_tcp"] = {"ok": True, "peer": str(connection.getpeername())}
except Exception as exc:
    results["internet_tcp"] = failed(exc)
print(json.dumps(results, ensure_ascii=True), flush=True)
'''


RESTRICTED_CMD_SOURCE = r'''@echo off
type "%P39_WORKSPACE%\seed.txt" > "%P39_WORKSPACE%\restricted-workspace-read.txt"
echo workspace_read_exit=%ERRORLEVEL%
> "%P39_WORKSPACE%\restricted-write.txt" echo restricted-write-ok
echo workspace_write_exit=%ERRORLEVEL%
type "%P39_OUTSIDE%\secret.txt" > "%P39_WORKSPACE%\restricted-outside-read.txt"
echo outside_read_exit=%ERRORLEVEL%
type "%USERPROFILE%\NTUSER.DAT" > "%P39_WORKSPACE%\restricted-profile-read.txt"
echo user_profile_read_exit=%ERRORLEVEL%
"%SYSTEMROOT%\System32\curl.exe" --noproxy "*" ^
  --connect-timeout 2 --max-time 4 -sS ^
  "http://127.0.0.1:%P39_LOOPBACK_PORT%/" ^
  -o "%P39_WORKSPACE%\restricted-loopback.bin"
echo loopback_exit=%ERRORLEVEL%
"%SYSTEMROOT%\System32\curl.exe" --noproxy "*" ^
  --connect-timeout 2 --max-time 4 -sS ^
  "http://1.1.1.1/" ^
  -o "%P39_WORKSPACE%\restricted-internet.bin"
echo internet_tcp_exit=%ERRORLEVEL%
echo probe_complete_exit=0
exit /b 0
'''


def parse_restricted_cmd(stdout: str) -> dict[str, dict[str, int | bool]]:
    observations: dict[str, dict[str, int | bool]] = {}
    for line in stdout.splitlines():
        key, separator, raw_value = line.strip().partition("=")
        if not separator or not key.endswith("_exit"):
            continue
        try:
            exit_code = int(raw_value)
        except ValueError:
            continue
        observations[key.removesuffix("_exit")] = {
            "ok": exit_code == 0,
            "exit_code": exit_code,
        }
    return observations


def main() -> int:
    profile_name = "P39.Probe." + uuid.uuid4().hex[:20]
    root = Path(tempfile.mkdtemp(prefix="p39_appcontainer_"))
    workspace = root / "workspace"
    outside = root / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "seed.txt").write_text("workspace-seed", encoding="utf-8")
    (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
    runtime = workspace / "python-runtime"
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for filename in (
        "python.exe",
        "python3.dll",
        "python312.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ):
        source = base / filename
        if source.exists():
            shutil.copy2(source, runtime / filename)
    shutil.copytree(base / "DLLs", runtime / "DLLs")
    shutil.copytree(base / "Lib", runtime / "Lib")
    child_script = workspace / "child_probe.py"
    child_script.write_text(CHILD_SOURCE, encoding="ascii")
    restricted_cmd_script = workspace / "restricted_probe.cmd"
    restricted_cmd_script.write_text(RESTRICTED_CMD_SOURCE, encoding="ascii")
    server, port, server_stop, server_thread = start_loopback_server()
    credential_target = "P39.Probe.Cred." + uuid.uuid4().hex
    probe_env_names = (
        "P39_WORKSPACE",
        "P39_OUTSIDE",
        "P39_LOOPBACK_PORT",
        "P39_CREDENTIAL_TARGET",
    )
    old_env = {key: os.environ.get(key) for key in probe_env_names}
    os.environ["P39_WORKSPACE"] = str(workspace)
    os.environ["P39_OUTSIDE"] = str(outside)
    os.environ["P39_LOOPBACK_PORT"] = str(port)
    os.environ["P39_CREDENTIAL_TARGET"] = credential_target
    sid = wintypes.LPVOID()
    restricted_token = None
    credential_created = False
    report: dict[str, object] = {
        "profile_name": profile_name,
        "workspace": str(workspace),
        "outside": str(outside),
        "parent_python": sys.executable,
        "base_python": sys._base_executable,
        "parent_loopback_baseline": verify_parent_loopback(port),
    }
    try:
        report["credential"] = create_disposable_credential(credential_target)
        credential_created = True
        sid, profile = create_profile(profile_name)
        report["profile"] = profile
        grant_workspace(workspace, str(profile["sid"]))
        report["workspace_acl_granted"] = True
        restricted_token = create_probe_restricted_token()
        cmd = os.path.join(os.environ["SYSTEMROOT"], "System32", "cmd.exe")
        python = str(runtime / "python.exe")
        report["host_venv_probe"] = {
            "purpose": "negative control: a venv launcher requires external pyvenv.cfg/runtime",
        }
        current_token_launch = launch(
            "CreateProcessAsUserW-current-token",
            sid,
            python,
            ["-I", str(child_script)],
            workspace,
        )
        restricted_token_launch = launch(
            "CreateProcessAsUserW-restricted-token",
            sid,
            cmd,
            ["/d", "/q", "/c", "call", str(restricted_cmd_script)],
            workspace,
            restricted_token,
        )
        restricted_python_launch = launch(
            "CreateProcessAsUserW-restricted-token-python",
            sid,
            python,
            ["-I", str(child_script)],
            workspace,
            restricted_token,
        )
        restricted_token_launch["child"] = parse_restricted_cmd(
            str(restricted_token_launch.get("stdout", ""))
        )
        report["controls"] = [
            launch(
                "CreateProcessW",
                sid,
                cmd,
                ["/d", "/c", "echo APP_CONTAINER_CMD_OK"],
                workspace,
            ),
            launch(
                "CreateProcessAsUserW-current-token-host-venv",
                sid,
                sys.executable,
                [str(child_script)],
                workspace,
            ),
        ]
        report["launches"] = [
            current_token_launch,
            restricted_token_launch,
            restricted_python_launch,
        ]
    except Exception as exc:
        report["fatal"] = {
            "type": type(exc).__name__,
            "text": str(exc),
            "winerror": getattr(exc, "winerror", None),
        }
    finally:
        if sid:
            advapi32.FreeSid(sid)
        if restricted_token is not None:
            restricted_token.Close()
        delete_hr = int(userenv.DeleteAppContainerProfile(profile_name))
        report["delete_profile_hresult"] = hex_hresult(delete_hr)
        if credential_created:
            report.setdefault("credential", {}).update(
                delete_disposable_credential(credential_target)
            )
        server_stop.set()
        server.close()
        server_thread.join(1)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(root, ignore_errors=True)
        report["temp_root_removed"] = not root.exists()

    launches = {
        str(item.get("api")): item
        for item in report.get("launches", [])
        if isinstance(item, dict)
    }
    restricted = launches.get("CreateProcessAsUserW-restricted-token-python", {})
    token = restricted.get("token", {}) if isinstance(restricted, dict) else {}
    child = restricted.get("child", {}) if isinstance(restricted, dict) else {}
    profile = report.get("profile", {})
    credential = report.get("credential", {})
    checks = {
        "no_fatal_error": "fatal" not in report,
        "parent_loopback_baseline": report.get("parent_loopback_baseline") is True,
        "credential_parent_visible": credential.get("parent_visible") is True,
        "credential_deleted": (
            credential.get("delete_succeeded") is True
            and credential.get("visible_after_delete") is False
        ),
        "restricted_child_created": restricted.get("created") is True,
        "restricted_child_exit_zero": restricted.get("exit_code") == 0,
        "token_is_appcontainer": token.get("is_appcontainer") is True,
        "token_is_restricted": token.get("is_restricted") is True,
        "token_is_low_integrity": token.get("integrity_sid") == "S-1-16-4096",
        "package_sid_matches_profile": (
            token.get("appcontainer_sid") == profile.get("sid")
        ),
        "workspace_read_allowed": child.get("workspace_read", {}).get("ok") is True,
        "workspace_write_allowed": child.get("workspace_write", {}).get("ok") is True,
        "outside_read_denied": child.get("outside_read", {}).get("ok") is False,
        "user_profile_read_denied": (
            child.get("user_profile_read", {}).get("ok") is False
        ),
        "credential_read_denied": (
            child.get("credential_read", {}).get("ok") is False
            and child.get("credential_read", {}).get("winerror") == 5
        ),
        "loopback_denied": child.get("loopback", {}).get("ok") is False,
        "internet_tcp_denied": child.get("internet_tcp", {}).get("ok") is False,
        "profile_deleted": report.get("delete_profile_hresult") == "0x00000000",
        "temp_root_removed": report.get("temp_root_removed") is True,
    }
    report["acceptance"] = {"passed": all(checks.values()), "checks": checks}
    report_path = Path(__file__).with_name("p39_appcontainer_probe_results.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"RESULT={report_path}")
    return 0 if report["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

