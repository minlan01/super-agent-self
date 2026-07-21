"""Unit tests for SSO service — OIDC configuration, state management, user provisioning."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from packages.auth.sso import SSOConfig, SSOService, _oauth_states


class TestSSOConfig:
    def test_default_config_disabled(self):
        config = SSOConfig()
        config._loaded = True
        assert config.enabled is False

    def test_is_enabled_requires_client_id(self):
        config = SSOConfig()
        config._loaded = True
        config.enabled = True
        config.client_id = ""
        service = SSOService(config)
        assert service.is_enabled is False

    def test_is_enabled_with_config(self):
        config = SSOConfig()
        config._loaded = True
        config.enabled = True
        config.client_id = "test-client"
        config.authorization_endpoint = "https://idp.example.com/auth"
        config.token_endpoint = "https://idp.example.com/token"
        config.userinfo_endpoint = "https://idp.example.com/userinfo"
        config.redirect_uri = "https://app.example.com/api/v1/auth/sso/callback"
        service = SSOService(config)
        assert service.is_enabled is True


class TestSSOServiceAuthorization:
    @pytest.mark.asyncio
    async def test_generate_authorization_url(self):
        config = SSOConfig()
        config._loaded = True
        config.enabled = True
        config.client_id = "test-client"
        config.client_secret = "test-secret"
        config.authorization_endpoint = "https://idp.example.com/auth"
        config.token_endpoint = "https://idp.example.com/token"
        config.userinfo_endpoint = "https://idp.example.com/userinfo"
        config.redirect_uri = "https://app.example.com/callback"
        config.scopes = ["openid", "profile"]
        config.nonce_enabled = True
        config.pkce_enabled = True
        service = SSOService(config)

        result = await service.get_authorization_url(redirect_to="/dashboard")
        assert "url" in result
        assert "state" in result
        assert "https://idp.example.com/auth" in result["url"]
        assert "client_id=test-client" in result["url"]
        assert "state=" in result["url"]
        assert "code_challenge=" in result["url"]

    @pytest.mark.asyncio
    async def test_sso_disabled_raises(self):
        config = SSOConfig()
        config._loaded = True
        config.enabled = False
        service = SSOService(config)
        with pytest.raises(ValueError, match="not configured"):
            await service.get_authorization_url()

    @pytest.mark.asyncio
    async def test_state_stored(self):
        config = SSOConfig()
        config._loaded = True
        config.enabled = True
        config.client_id = "test"
        config.authorization_endpoint = "https://idp.example.com/auth"
        config.token_endpoint = "https://idp.example.com/token"
        config.userinfo_endpoint = "https://idp.example.com/userinfo"
        config.redirect_uri = "https://app.example.com/callback"
        service = SSOService(config)

        _oauth_states.clear()
        result = await service.get_authorization_url()
        state = result["state"]
        assert state in _oauth_states


class TestSSOServiceCallback:
    @pytest.mark.asyncio
    async def test_invalid_state_raises(self):
        config = SSOConfig()
        config._loaded = True
        service = SSOService(config)
        with pytest.raises(ValueError, match="Invalid or expired"):
            await service.handle_callback("code", "nonexistent-state")


class TestSSOServiceUserInfo:
    def test_find_or_create_user_existing_sso(self, tmp_path):
        """Test finding an existing SSO user by sso_id."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from packages.db.models import Base, User

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)

        # Create existing SSO user
        from packages.db.repositories.auth_repo import AuthRepository
        user = AuthRepository.create_user(db, username="ssouser", password="pass")
        user.sso_id = "google-12345"
        user.sso_provider = "google"
        user.auth_method = AuthMethod.SSO
        db.flush()

        config = SSOConfig()
        config._loaded = True
        config.provider = "google"
        config.auto_create_users = True
        service = SSOService(config)

        found_user, is_new = service.find_or_create_user(db, {"sub": "google-12345", "email": "sso@example.com"})
        assert found_user.id == user.id
        assert is_new is False

    def test_find_or_create_user_jit_provisioning(self):
        """Test JIT user creation from SSO."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from packages.db.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)

        # Seed default role
        from packages.db.repositories.rbac_repo import RBACRepository
        RBACRepository.seed_default_roles_and_permissions(db)

        config = SSOConfig()
        config._loaded = True
        config.provider = "google"
        config.auto_create_users = True
        config.default_role_on_create = "user"
        service = SSOService(config)

        new_user, is_new = service.find_or_create_user(db, {
            "sub": "new-sso-123",
            "email": "new@example.com",
            "name": "New User",
        })
        assert is_new is True
        assert new_user.username == "new_user"
        assert new_user.sso_id == "new-sso-123"
        assert new_user.auth_method == AuthMethod.SSO

    def test_find_or_create_user_disabled_auto_create(self):
        """Test that auto_create_users=False prevents new user creation."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from packages.db.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)

        config = SSOConfig()
        config._loaded = True
        config.provider = "google"
        config.auto_create_users = False
        service = SSOService(config)

        with pytest.raises(ValueError, match="Auto user creation is disabled"):
            service.find_or_create_user(db, {"sub": "new-123", "email": "new@example.com"})

    def test_get_provider_info(self):
        config = SSOConfig()
        config._loaded = True
        config.enabled = False
        service = SSOService(config)
        assert service.get_provider_info() == {}


# Import AuthMethod for SSO tests
from packages.db.models import AuthMethod
