"""Integration tests for Vision API endpoints — /api/v1/vision/analyze and /ocr."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.db.models import Base
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


@pytest.fixture
def app_and_client():
    _prev_require_auth = os.environ.get("REQUIRE_AUTH")
    os.environ["REQUIRE_AUTH"] = "1"
    clear_settings_cache()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    RBACRepository.seed_default_roles_and_permissions(db)
    db.commit()

    from packages.db.session import get_db
    from apps.api_server.main import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    yield client, db

    app.dependency_overrides.clear()
    db.close()
    if _prev_require_auth is not None:
        os.environ["REQUIRE_AUTH"] = _prev_require_auth
    else:
        os.environ.pop("REQUIRE_AUTH", None)


@pytest.fixture
def admin_token(app_and_client):
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"
    db.commit()
    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()
    return create_access_token({"sub": user.id, "username": user.username})


class TestVisionAuth:
    def test_analyze_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.post("/api/v1/vision/analyze")
        assert resp.status_code in (401, 403)

    def test_ocr_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.post("/api/v1/vision/ocr")
        assert resp.status_code in (401, 403)


class TestVisionEndpoints:
    def test_analyze_with_valid_image(self, app_and_client, admin_token):
        client, _ = app_and_client
        # Create minimal PNG
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "A simple test image"}}]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"VISION_API_URL": "http://test-api"}):
            resp = client.post(
                "/api/v1/vision/analyze",
                files={"file": ("test.png", png_data, "image/png")},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_ocr_endpoint(self, app_and_client, admin_token):
        client, _ = app_and_client
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        with patch("packages.vision.vision_service.OCRService") as MockOCR:
            MockOCR.return_value.is_available = True
            MockOCR.return_value.extract_text.return_value = "test text"
            resp = client.post(
                "/api/v1/vision/ocr",
                files={"file": ("test.png", png_data, "image/png")},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["text"] == "test text"
