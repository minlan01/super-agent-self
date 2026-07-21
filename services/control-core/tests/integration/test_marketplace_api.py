"""Integration tests for Skill Marketplace API endpoints."""

import os
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base, Edition, Skill, SkillStatus
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


@pytest.fixture
def app_and_client():
    """Create a test app with RBAC enabled and REQUIRE_AUTH=true."""
    _prev_require_auth = os.environ.get("REQUIRE_AUTH")
    os.environ["REQUIRE_AUTH"] = "1"
    clear_settings_cache()

    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)

    # Seed RBAC
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
def admin_user_and_token(app_and_client):
    """Create an admin user with admin token."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"  # type: ignore
    db.commit()

    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return user, token, db


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_skill(db: Session, name: str = "test-skill", edition: str = "personal") -> Skill:
    """Insert a stable skill row for testing."""
    skill = Skill(
        name=name,
        edition=Edition(edition),
        status=SkillStatus.STABLE,
        version=1,
        definition={"tags": ["test"]},
        description="A test skill",
    )
    db.add(skill)
    db.flush()
    db.refresh(skill)
    return skill


# ── Browse ──────────────────────────────────────────────────────────────────


class TestBrowseSkills:
    @pytest.mark.integration
    def test_browse_returns_empty(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token
        resp = client.get("/api/v1/marketplace/browse", headers=_auth_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    @pytest.mark.integration
    def test_browse_returns_published_skill(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        _seed_skill(db, "visible-skill")
        db.commit()

        resp = client.get("/api/v1/marketplace/browse", headers=_auth_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["name"] == "visible-skill"

    @pytest.mark.integration
    def test_browse_filter_by_edition(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        _seed_skill(db, "personal-skill", edition="personal")
        _seed_skill(db, "enterprise-skill", edition="enterprise")
        db.commit()

        resp = client.get(
            "/api/v1/marketplace/browse?edition=personal",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["name"] == "personal-skill"

    @pytest.mark.integration
    def test_browse_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/marketplace/browse")
        assert resp.status_code in (401, 403)


# ── Subscription ────────────────────────────────────────────────────────────


class TestSubscription:
    @pytest.mark.integration
    def test_subscribe_to_skill(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        user, token, _ = admin_user_and_token
        skill = _seed_skill(db)
        db.commit()

        resp = client.post(
            "/api/v1/marketplace/subscribe",
            json={"skill_id": skill.id},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["skill_id"] == skill.id

    @pytest.mark.integration
    def test_list_subscriptions_empty(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.get(
            "/api/v1/marketplace/subscriptions",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    @pytest.mark.integration
    def test_list_subscriptions_after_subscribe(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db)
        db.commit()

        client.post(
            "/api/v1/marketplace/subscribe",
            json={"skill_id": skill.id},
            headers=_auth_headers(token),
        )

        resp = client.get(
            "/api/v1/marketplace/subscriptions",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["skill_name"] == "test-skill"

    @pytest.mark.integration
    def test_unsubscribe_skill(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db)
        db.commit()

        # Subscribe first
        client.post(
            "/api/v1/marketplace/subscribe",
            json={"skill_id": skill.id},
            headers=_auth_headers(token),
        )

        # Then unsubscribe
        resp = client.post(
            f"/api/v1/marketplace/unsubscribe/{skill.id}",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    @pytest.mark.integration
    def test_unsubscribe_nonexistent_returns_404(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.post(
            "/api/v1/marketplace/unsubscribe/nonexistent-id",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404


# ── Rating ──────────────────────────────────────────────────────────────────


class TestRating:
    @pytest.mark.integration
    def test_rate_skill(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db)
        db.commit()

        resp = client.post(
            "/api/v1/marketplace/rate",
            json={"skill_id": skill.id, "rating": 5, "review": "Great!"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["rating"] == 5

    @pytest.mark.integration
    def test_get_skill_ratings(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db)
        db.commit()

        # Rate the skill first
        client.post(
            "/api/v1/marketplace/rate",
            json={"skill_id": skill.id, "rating": 4},
            headers=_auth_headers(token),
        )

        resp = client.get(
            f"/api/v1/marketplace/{skill.id}/ratings",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["rating"] == 4


# ── Cross-Edition Promotion ────────────────────────────────────────────────


class TestPromotion:
    @pytest.mark.integration
    def test_promote_skill(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db, edition="personal")
        db.commit()

        resp = client.post(
            "/api/v1/marketplace/promote",
            json={
                "skill_id": skill.id,
                "source_edition": "personal",
                "target_edition": "enterprise",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "pending"

    @pytest.mark.integration
    def test_promote_same_edition_returns_400(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db, edition="personal")
        db.commit()

        resp = client.post(
            "/api/v1/marketplace/promote",
            json={
                "skill_id": skill.id,
                "source_edition": "personal",
                "target_edition": "personal",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400

    @pytest.mark.integration
    def test_list_promotions_empty(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.get(
            "/api/v1/marketplace/promotions",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    @pytest.mark.integration
    def test_list_promotions_after_promote(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db, edition="personal")
        db.commit()

        client.post(
            "/api/v1/marketplace/promote",
            json={
                "skill_id": skill.id,
                "source_edition": "personal",
                "target_edition": "enterprise",
            },
            headers=_auth_headers(token),
        )

        resp = client.get(
            "/api/v1/marketplace/promotions",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["skill_name"] == "test-skill"
        assert body["data"][0]["status"] == "pending"


# ── Review Promotion ────────────────────────────────────────────────────────


class TestReviewPromotion:
    @pytest.mark.integration
    def test_review_promotion_approve(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db, edition="personal")
        db.commit()

        # Create a promotion first
        promo_resp = client.post(
            "/api/v1/marketplace/promote",
            json={
                "skill_id": skill.id,
                "source_edition": "personal",
                "target_edition": "enterprise",
            },
            headers=_auth_headers(token),
        )
        promotion_id = promo_resp.json()["data"]["promotion_id"]

        # Approve the promotion
        resp = client.post(
            f"/api/v1/marketplace/promotions/{promotion_id}/review",
            json={"approved": True, "note": "Looks good"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "approved"

    @pytest.mark.integration
    def test_review_promotion_reject(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db, edition="personal")
        db.commit()

        # Create a promotion
        promo_resp = client.post(
            "/api/v1/marketplace/promote",
            json={
                "skill_id": skill.id,
                "source_edition": "personal",
                "target_edition": "enterprise",
            },
            headers=_auth_headers(token),
        )
        promotion_id = promo_resp.json()["data"]["promotion_id"]

        # Reject the promotion
        resp = client.post(
            f"/api/v1/marketplace/promotions/{promotion_id}/review",
            json={"approved": False, "note": "Not ready"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "rejected"

    @pytest.mark.integration
    def test_review_promotion_not_found(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.post(
            "/api/v1/marketplace/promotions/nonexistent-id/review",
            json={"approved": True},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_review_promotion_already_reviewed(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        skill = _seed_skill(db, edition="personal")
        db.commit()

        # Create and approve a promotion
        promo_resp = client.post(
            "/api/v1/marketplace/promote",
            json={
                "skill_id": skill.id,
                "source_edition": "personal",
                "target_edition": "enterprise",
            },
            headers=_auth_headers(token),
        )
        promotion_id = promo_resp.json()["data"]["promotion_id"]

        client.post(
            f"/api/v1/marketplace/promotions/{promotion_id}/review",
            json={"approved": True},
            headers=_auth_headers(token),
        )

        # Try to review again — should return 400
        resp = client.post(
            f"/api/v1/marketplace/promotions/{promotion_id}/review",
            json={"approved": False},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400
