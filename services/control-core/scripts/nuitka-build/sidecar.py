"""Minimal Windows sidecar for the Tauri spike."""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

HTTP_PORT: Final = int(os.environ.get("ZCODE_HTTP_PORT", "9876"))
RUN_NONCE: Final = os.environ.get("ZCODE_RUN_NONCE", "development")
PIPE_PATH: Final = r"\\.\pipe\zcode-sidecar-spike"
BUFFER_SIZE: Final = 64 * 1024
PIPE_ACCESS_DUPLEX = 0x3
PIPE_TYPE_MESSAGE = 0x4
PIPE_READMODE_MESSAGE = 0x2
PIPE_WAIT = 0x0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
PIPE_UNLIMITED_INSTANCES = 255
ERROR_PIPE_CONNECTED = 535
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CreateNamedPipeW = kernel32.CreateNamedPipeW
CreateNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
CreateNamedPipeW.restype = ctypes.c_void_p
ConnectNamedPipe = kernel32.ConnectNamedPipe
ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
ConnectNamedPipe.restype = ctypes.c_int
DisconnectNamedPipe = kernel32.DisconnectNamedPipe
DisconnectNamedPipe.argtypes = [ctypes.c_void_p]
DisconnectNamedPipe.restype = ctypes.c_int
ReadFile = kernel32.ReadFile
ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
ReadFile.restype = ctypes.c_int
WriteFile = kernel32.WriteFile
WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
WriteFile.restype = ctypes.c_int
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [ctypes.c_void_p]
CloseHandle.restype = ctypes.c_int


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/health":
            body = json.dumps(
                {"status": "ready", "nonce": RUN_NONCE, "pid": os.getpid()},
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *_args: object) -> None:
        return


class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def pipe_echo_server(stop: threading.Event) -> None:
    while not stop.is_set():
        handle = CreateNamedPipeW(PIPE_PATH, PIPE_ACCESS_DUPLEX, PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, PIPE_UNLIMITED_INSTANCES, BUFFER_SIZE, BUFFER_SIZE, 0, None)
        if handle in (None, 0, INVALID_HANDLE_VALUE):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            connected = ConnectNamedPipe(handle, None)
            if not connected and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
                continue
            while not stop.is_set():
                buffer = ctypes.create_string_buffer(BUFFER_SIZE)
                read = ctypes.c_uint32()
                if not ReadFile(handle, buffer, BUFFER_SIZE, ctypes.byref(read), None) or read.value == 0:
                    break
                try:
                    request = json.loads(buffer.raw[:read.value].decode("utf-8"))
                    if request.get("nonce") != RUN_NONCE:
                        response_data = {"error": "run nonce mismatch", "nonce": RUN_NONCE}
                    else:
                        response_data = {
                            "echoed": request.get("msg", ""),
                            "nonce": RUN_NONCE,
                            "t": time.time(),
                        }
                    response = json.dumps(response_data, separators=(",", ":")).encode("utf-8")
                except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                    response = b'{"error":"invalid request"}'
                written = ctypes.c_uint32()
                if not WriteFile(handle, response, len(response), ctypes.byref(written), None):
                    break
        finally:
            DisconnectNamedPipe(handle)
            CloseHandle(handle)


def main() -> None:
    stop = threading.Event()
    http = ReusableHTTPServer(("127.0.0.1", HTTP_PORT), HealthHandler)
    threading.Thread(target=http.serve_forever, name="health", daemon=True).start()
    threading.Thread(target=pipe_echo_server, args=(stop,), name="pipe", daemon=True).start()
    try:
        while True:
            time.sleep(0.25)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        stop.set()
        http.shutdown()
        http.server_close()


if __name__ == "__main__":
    main()
