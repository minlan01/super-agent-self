"""Tests for the Sidecar's two-stage desktop API startup."""

from __future__ import annotations

import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.platform.windows.sidecar_host import DeferredDesktopApplication


def _loaded_application() -> FastAPI:
    application = FastAPI()

    @application.get("/loaded")
    def loaded() -> dict[str, bool]:
        return {"loaded": True}

    return application


def test_health_is_available_while_desktop_api_loads() -> None:
    release = threading.Event()

    def loader() -> FastAPI:
        release.wait(timeout=5)
        return _loaded_application()

    with TestClient(DeferredDesktopApplication(loader, timeout=3)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["api_ready"] is False

        release.set()
        loaded = client.get("/loaded")
        assert loaded.status_code == 200
        assert loaded.json() == {"loaded": True}
        assert client.app.initialization_complete.is_set()


def test_non_health_request_waits_for_desktop_api() -> None:
    release = threading.Event()

    def loader() -> FastAPI:
        release.wait(timeout=5)
        return _loaded_application()

    timer = threading.Timer(0.25, release.set)
    timer.start()
    try:
        with TestClient(DeferredDesktopApplication(loader, timeout=3)) as client:
            response = client.get("/loaded")
            assert response.status_code == 200
            assert response.json() == {"loaded": True}
    finally:
        timer.cancel()
        release.set()


def test_loader_failure_returns_service_unavailable() -> None:
    def loader() -> FastAPI:
        raise RuntimeError("test loader failure")

    with TestClient(DeferredDesktopApplication(loader, timeout=3)) as client:
        response = client.get("/loaded")

    assert response.status_code == 503
    assert response.json() == {"detail": "control-core desktop API initialization failed"}
