"""SSO Service — OIDC-based Single Sign-On integration."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger()

_sso_http_client: Any | None = None
_sso_http_client_lock = threading.Lock()


async def _get_sso_http_client() -> Any:
    import httpx
    global _sso_http_client
    with _sso_http_client_lock:
        if _sso_http_client is None or _sso_http_client.is_closed:
            _sso_http_client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )
    return _sso_http_client


class SSOConfig:
    """SSO/OIDC configuration loaded from configs."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self.provider: str = ""
        self.issuer: str = ""
        self.authorization_endpoint: str = ""
        self.token_endpoint: str = ""
        self.userinfo_endpoint: str = ""
        self.client_id: str = ""
        self.client_secret: str = ""
        self.redirect_uri: str = ""
        self.scopes: list[str] = ["openid", "profile", "email"]
        self.auto_create_users: bool = True
        self.default_role_on_create: str = "user"
        self.nonce_enabled: bool = True
        self.pkce_enabled: bool = True
        self._loaded = False

    async def load(self) -> None:
        if self._loaded:
            return
        config_path = Path("configs/app.yaml")
        if not config_path.exists():
            self._loaded = True
            return

        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            sso = cfg.get("sso", {})
            self.enabled = sso.get("enabled", False)

            oidc = sso.get("oidc", {})
            self.provider = oidc.get("provider", "")
            self.issuer = oidc.get("issuer", "")
            self.authorization_endpoint = oidc.get("authorization_endpoint", "")
            self.token_endpoint = oidc.get("token_endpoint", "")
            self.userinfo_endpoint = oidc.get("userinfo_endpoint", "")
            self.client_id = oidc.get("client_id", "")
            self.client_secret = oidc.get("client_secret", "")
            self.redirect_uri = oidc.get("redirect_uri", "")
            self.scopes = oidc.get("scopes", ["openid", "profile", "email"])
            self.auto_create_users = oidc.get("auto_create_users", True)
            self.default_role_on_create = oidc.get("default_role_on_create", "user")
            self.nonce_enabled = oidc.get("nonce_enabled", True)
            self.pkce_enabled = oidc.get("pkce_enabled", True)

            if self.issuer and not self.authorization_endpoint:
                await self._discover_endpoints()

            if self.enabled:
                missing = []
                if not self.client_id:
                    missing.append("client_id")
                if not self.issuer:
                    missing.append("issuer")
                if not self.client_secret and not self.pkce_enabled:
                    missing.append("client_secret (or enable pkce_enabled)")
                if missing:
                    self.enabled = False
                    logger.error(
                        "SSO enabled but required fields missing: %s — SSO disabled",
                        ", ".join(missing),
                    )

            self._loaded = True
            logger.info("SSO config loaded: enabled=%s, provider=%s", self.enabled, self.provider)
        except Exception:
            logger.exception("Failed to load SSO config — will retry on next access")

    async def _discover_endpoints(self) -> None:
        try:
            client = await _get_sso_http_client()
            well_known_url = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
            resp = await client.get(well_known_url, timeout=10)
            if resp.status_code == 200:
                doc = resp.json()
                if not self.authorization_endpoint:
                    self.authorization_endpoint = doc.get("authorization_endpoint", "")
                if not self.token_endpoint:
                    self.token_endpoint = doc.get("token_endpoint", "")
                if not self.userinfo_endpoint:
                    self.userinfo_endpoint = doc.get("userinfo_endpoint", "")
                logger.info("OIDC discovery successful from %s", self.issuer)
        except Exception as e:
            logger.warning("OIDC discovery failed for %s: %s", self.issuer, e)


# Module-level state storage for OAuth states and PKCE verifiers
_oauth_states: dict[str, dict[str, str]] = {}  # state -> {nonce, code_verifier, redirect_to, created_at}
_MAX_OAUTH_STATES = 2000

# In-memory one-time code store for secure SSO token exchange: {code: {"token": str, "created_at": float}}
_sso_codes: dict[str, dict] = {}
_MAX_SSO_CODES = 1000

_state_lock = threading.Lock()


def generate_auth_code(token: str) -> str:
    code = secrets.token_urlsafe(32)
    with _state_lock:
        _sso_codes[code] = {"token": token, "created_at": time.time()}
        if len(_sso_codes) > _MAX_SSO_CODES * 2:
            _evict_sso_codes_unlocked()
    return code


def _evict_sso_codes_unlocked() -> None:
    now = time.time()
    expired = [k for k, v in _sso_codes.items() if now - v["created_at"] > 120]
    for k in expired:
        _sso_codes.pop(k, None)
    if len(_sso_codes) > _MAX_SSO_CODES:
        sorted_keys = sorted(_sso_codes, key=lambda k: _sso_codes[k]["created_at"])
        for k in sorted_keys[: len(_sso_codes) - _MAX_SSO_CODES]:
            _sso_codes.pop(k, None)


def exchange_auth_code(code: str) -> str | None:
    """Exchange a one-time code for the token. Returns None if invalid/expired."""
    with _state_lock:
        entry = _sso_codes.pop(code, None)  # Single-use: remove on read
    if entry is None:
        return None
    # 60 second expiry
    if time.time() - entry["created_at"] > 60:
        return None
    return entry["token"]


def _cleanup_expired_states_unlocked() -> None:
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - float(v.get("created_at", "0")) > 600]
    for k in expired:
        _oauth_states.pop(k, None)


def _evict_oauth_states_unlocked() -> None:
    _cleanup_expired_states_unlocked()
    if len(_oauth_states) > _MAX_OAUTH_STATES:
        sorted_keys = sorted(_oauth_states, key=lambda k: float(_oauth_states[k].get("created_at", "0")))
        for k in sorted_keys[: len(_oauth_states) - _MAX_OAUTH_STATES]:
            _oauth_states.pop(k, None)


class _RedisStateBackend:
    """Optional Redis-backed SSO state storage for multi-process deployments."""

    def __init__(self, redis_client, prefix="sso:"):
        self._r = redis_client
        self._prefix = prefix

    def save_state(self, state: str, data: dict) -> None:
        self._r.setex(f"{self._prefix}state:{state}", 600, json.dumps(data))

    def pop_state(self, state: str) -> dict | None:
        key = f"{self._prefix}state:{state}"
        raw = self._r.get(key)
        if raw:
            self._r.delete(key)
            return json.loads(raw)
        return None

    def save_code(self, code: str, data: dict) -> None:
        self._r.setex(f"{self._prefix}code:{code}", 60, json.dumps(data))

    def pop_code(self, code: str) -> dict | None:
        key = f"{self._prefix}code:{code}"
        raw = self._r.get(key)
        if raw:
            self._r.delete(key)
            return json.loads(raw)
        return None


class SSOService:
    """OIDC SSO service for login, callback, and user provisioning."""

    def __init__(self, config: SSOConfig | None = None, state_backend=None):
        self._config = config or SSOConfig()
        self._state_backend = state_backend

    @property
    def config(self) -> SSOConfig:
        if not self._config._loaded:
            import asyncio
            try:
                asyncio.get_running_loop()
                logger.warning("SSO config not loaded — call await sso_service.ensure_loaded() first")
            except RuntimeError:
                asyncio.run(self._config.load())
        return self._config

    async def ensure_loaded(self) -> SSOConfig:
        if not self._config._loaded:
            await self._config.load()
        return self._config

    @property
    def is_enabled(self) -> bool:
        return self.config.enabled and bool(self.config.client_id)

    async def get_authorization_url(self, redirect_to: str = "/") -> dict[str, str]:
        if not self.is_enabled:
            raise ValueError("SSO is not configured")

        await self.ensure_loaded()

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32) if self.config.nonce_enabled else ""
        code_verifier = secrets.token_urlsafe(48) if self.config.pkce_enabled else ""

        state_data = {
            "nonce": nonce,
            "code_verifier": code_verifier,
            "redirect_to": redirect_to,
            "created_at": str(int(time.time())),
        }

        if self._state_backend is not None:
            self._state_backend.save_state(state, state_data)
        else:
            with _state_lock:
                _cleanup_expired_states_unlocked()
                if len(_oauth_states) > _MAX_OAUTH_STATES:
                    _evict_oauth_states_unlocked()
                _oauth_states[state] = state_data

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
        }

        if nonce:
            params["nonce"] = nonce

        if code_verifier:
            # PKCE code_challenge (S256)
            import base64
            challenge_bytes = hashlib.sha256(code_verifier.encode("ascii")).digest()
            code_challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode("ascii")
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        auth_url = f"{self.config.authorization_endpoint}?{urllib.parse.urlencode(params)}"
        return {"url": auth_url, "state": state}

    async def handle_callback(self, code: str, state: str) -> dict[str, Any]:
        await self.ensure_loaded()

        if self._state_backend is not None:
            state_data = self._state_backend.pop_state(state)
        else:
            with _state_lock:
                _cleanup_expired_states_unlocked()
                state_data = _oauth_states.pop(state, None)
        if not state_data:
            raise ValueError("Invalid or expired OAuth state")

        # Check state age (max 10 minutes)
        created_at = int(state_data.get("created_at", "0"))
        if time.time() - created_at > 600:
            raise ValueError("OAuth state expired")

        # Exchange code for tokens
        token_data = await self._exchange_code(code, state_data)
        if not token_data:
            raise ValueError("Failed to exchange authorization code")

        # Get user info
        access_token = token_data.get("access_token", "")
        user_info = await self._get_user_info(access_token)
        if not user_info:
            raise ValueError("Failed to get user info from provider")

        return {
            "user_info": user_info,
            "state_data": state_data,
            "id_token": token_data.get("id_token"),
        }

    async def _exchange_code(self, code: str, state_data: dict) -> dict | None:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }

        if state_data.get("code_verifier"):
            data["code_verifier"] = state_data["code_verifier"]

        try:
            client = await _get_sso_http_client()
            resp = await client.post(self.config.token_endpoint, data=data, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error("Token exchange failed: HTTP %s", resp.status_code)
                return None
        except Exception:
            logger.exception("Token exchange error")
            return None

    async def _get_user_info(self, access_token: str) -> dict | None:
        try:
            client = await _get_sso_http_client()
            resp = await client.get(
                self.config.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error("Userinfo request failed: HTTP %s", resp.status_code)
                return None
        except Exception:
            logger.exception("Userinfo error")
            return None

    def find_or_create_user(self, db: Session, user_info: dict) -> tuple[Any, bool]:
        """Find existing user by SSO ID or create a new one (JIT provisioning).

        Returns (user, is_new_user)
        """
        from sqlalchemy import select

        from packages.db.models import AuthMethod, User
        from packages.db.repositories.auth_repo import AuthRepository

        sso_id = user_info.get("sub", "")
        email = user_info.get("email", "")
        name = user_info.get("name", "") or user_info.get("preferred_username", "") or email.split("@")[0]

        # Try to find by SSO ID
        existing = db.scalar(select(User).where(User.sso_id == sso_id)) if sso_id else None
        if existing:
            return existing, False

        # Try to find by email (link existing account)
        if email:
            existing = db.scalar(select(User).where(User.email == email))
            if existing:
                # Link SSO to existing account
                existing.sso_id = sso_id
                existing.sso_provider = self.config.provider
                existing.auth_method = AuthMethod.SSO
                db.flush()
                return existing, False

        # Create new user (JIT provisioning)
        if not self.config.auto_create_users:
            raise ValueError("Auto user creation is disabled")

        # Generate a unique username
        base_username = name.lower().replace(" ", "_").replace(".", "_")
        username = base_username
        counter = 1
        while db.scalar(select(User).where(User.username == username)):
            username = f"{base_username}_{counter}"
            counter += 1

        # Generate random password (SSO users don't need one, but field is required)
        import secrets as sec
        random_password = sec.token_urlsafe(32)
        hashed_pw = AuthRepository._hash_password(random_password)

        user = User(
            username=username,
            email=email,
            hashed_password=hashed_pw,
            sso_id=sso_id,
            sso_provider=self.config.provider,
            auth_method=AuthMethod.SSO,
        )
        db.add(user)
        db.flush()

        # Assign default role
        try:
            from packages.db.repositories.rbac_repo import RBACRepository
            RBACRepository.assign_default_role(db, user.id)
        except Exception as e:
            logger.warning("Failed to assign default role to SSO user %s: %s", user.id, e)

        return user, True

    def get_provider_info(self) -> dict[str, str]:
        """Get provider display info for the frontend."""
        if not self.is_enabled:
            return {}
        return {
            "provider": self.config.provider,
            "display_name": self.config.provider.replace("-", " ").replace("_", " ").title(),
        }


# Module-level singleton
_sso_service: SSOService | None = None


async def get_sso_service() -> SSOService:
    global _sso_service
    if _sso_service is None:
        config = SSOConfig()
        await config.load()
        _sso_service = SSOService(config)
    return _sso_service
