"""Authentication routes — register, login, and current-user info."""

import asyncio
import logging
import time
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db
from packages.agent_core.schemas import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
    ResponseBase,
    SSOCallbackRequest,
    SSOLoginResponse,
    SSOProvidersResponse,
    SSOTokenResponse,
    UserResponse,
)
from packages.auth.auth_service import create_access_token
from packages.auth.sso import generate_auth_code, get_sso_service
from packages.config import get_settings
from packages.db.models import AuditEventType, User
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.agent_core.schemas import AuditEventCreate

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300
_FAILED_LOGIN_CLEANUP_INTERVAL = 300
_failed_login_store: dict[str, list[float]] = {}
_failed_login_lock = threading.Lock()
_failed_login_last_cleanup: float = 0.0


def _cleanup_failed_login_store() -> None:
    global _failed_login_last_cleanup
    now = time.time()
    if now - _failed_login_last_cleanup < _FAILED_LOGIN_CLEANUP_INTERVAL:
        return
    stale_keys = [
        k for k, v in _failed_login_store.items()
        if not v or now - v[-1] > _LOCKOUT_SECONDS
    ]
    for k in stale_keys:
        del _failed_login_store[k]
    _failed_login_last_cleanup = now


def _check_login_lockout(username: str) -> None:
    with _failed_login_lock:
        _cleanup_failed_login_store()
        attempts = _failed_login_store.get(username, [])
        now = time.time()
        attempts = [t for t in attempts if now - t < _LOCKOUT_SECONDS]
        _failed_login_store[username] = attempts
        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            remaining = int(_LOCKOUT_SECONDS - (now - attempts[0]))
            raise HTTPException(
                status_code=429,
                detail=f"Account temporarily locked. Try again in {remaining}s.",
            )


def _record_failed_login(username: str) -> None:
    with _failed_login_lock:
        now = time.time()
        attempts = _failed_login_store.get(username, [])
        attempts = [t for t in attempts if now - t < _LOCKOUT_SECONDS]
        attempts.append(now)
        _failed_login_store[username] = attempts


def _clear_failed_logins(username: str) -> None:
    with _failed_login_lock:
        _failed_login_store.pop(username, None)


def _validate_csrf(request: Request) -> None:
    """Lightweight CSRF check for cookie-based auth.

    Since our login endpoint uses JSON body (not form submission),
    browsers won't send cross-origin POST with JSON content type.
    We additionally verify a custom header or Origin for defense-in-depth.
    """
    origin = request.headers.get("origin", "")
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        host = request.headers.get("host", "")
        if host and parsed.netloc != host:
            raise HTTPException(status_code=403, detail="CSRF check failed: origin mismatch")


# ── Routes ────────────────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a new user",
    description="Create a new user account with username, password, and optional email. Passwords are hashed with bcrypt.",
)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account."""
    # Check if username already exists
    existing = AuthRepository.get_by_username(db, body.username)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = AuthRepository.create_user(
        db,
        username=body.username,
        password=body.password,
        email=body.email,
    )

    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.USER_REGISTERED,
        actor=user.id,
        detail={"username": user.username},
    ))

    return RegisterResponse(success=True, data=UserResponse.model_validate(user))


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate user",
    description="Validate credentials and return a signed JWT token for subsequent API calls.",
)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate and return a signed token.

    Sets an httpOnly ``access_token`` cookie in addition to returning
    the token in the response body (for backward compatibility with
    API clients that use the Authorization header).
    """
    _validate_csrf(request)
    _check_login_lockout(body.username)
    user = AuthRepository.get_by_username(db, body.username)
    if user is None or not AuthRepository.verify_password(body.password, user.hashed_password):
        _record_failed_login(body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    _clear_failed_logins(body.username)

    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.USER_LOGIN,
        actor=user.id,
        detail={"username": user.username, "auth_method": "local"},
    ))

    token = create_access_token(data={"sub": user.id, "username": user.username})
    settings = get_settings()
    expire_minutes = settings.security.token_expire_minutes

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=expire_minutes * 60,
        path="/api/v1",
    )

    return LoginResponse(
        success=True,
        data={"token": token, "user": UserResponse.model_validate(user)},
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user",
    description="Return the currently authenticated user's profile. When REQUIRE_AUTH=false, returns the default admin.",
)
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's info.

    When ``REQUIRE_AUTH=false`` this always returns the default admin.
    When ``REQUIRE_AUTH=true`` a valid ``Authorization: Bearer <token>``
    header must be supplied.
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return MeResponse(success=True, data=UserResponse.model_validate(current_user))


@router.post(
    "/logout",
    response_model=ResponseBase,
    summary="Logout user",
    description="Clear the httpOnly access_token cookie.",
)
def logout(response: Response):
    """Clear the httpOnly access_token cookie."""
    response.delete_cookie(key="access_token", path="/api/v1")
    return {"success": True, "message": "Logged out"}


# ── SSO endpoints ──────────────────────────────────────────────────────


@router.get("/sso/providers", response_model=SSOProvidersResponse)
async def sso_providers():
    """List available SSO providers."""
    sso = await get_sso_service()
    if not sso.is_enabled:
        return SSOProvidersResponse(data=[])
    info = sso.get_provider_info()
    if not info:
        return SSOProvidersResponse(data=[])

    auth_result = await sso.get_authorization_url()
    return SSOProvidersResponse(data=[{
        "provider": info["provider"],
        "display_name": info["display_name"],
        "login_url": f"/api/v1/auth/sso/login?state={auth_result['state']}",
    }])


@router.get("/sso/login")
async def sso_login(redirect_to: str = "/"):
    """Initiate SSO login — redirects to the IdP."""
    from fastapi.responses import RedirectResponse
    sso = await get_sso_service()
    if not sso.is_enabled:
        raise HTTPException(status_code=400, detail="SSO is not configured")

    # Prevent open redirect — only allow relative URLs
    if not redirect_to.startswith("/") or redirect_to.startswith("//"):
        redirect_to = "/"

    result = await sso.get_authorization_url(redirect_to=redirect_to)
    return RedirectResponse(url=result["url"])


async def _process_sso_login(code: str, state: str | None, db: Session):
    """Shared SSO login logic: exchange code, find/create user, issue token.

    Returns ``(user, is_new_user, token)`` on success.
    Raises ``ValueError`` on SSO validation failures.
    """
    sso = await get_sso_service()
    if not sso.is_enabled:
        raise HTTPException(status_code=400, detail="SSO is not configured")

    result = await sso.handle_callback(code, state or "")
    user_info = result["user_info"]
    state_data = result.get("state_data", {})

    user, is_new_user = sso.find_or_create_user(db, user_info)
    db.flush()

    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.SSO_USER_CREATED if is_new_user else AuditEventType.SSO_LOGIN,
        actor=user.id,
        detail={"username": user.username, "is_new_user": is_new_user},
    ))

    token = create_access_token({"sub": user.id, "username": user.username})
    return user, is_new_user, token, state_data


@router.get("/sso/callback")
async def sso_callback(code: str, state: str | None = None, db: Session = Depends(get_db)):
    """Handle SSO callback — exchange code, create/link user, issue token."""
    from fastapi.responses import RedirectResponse

    try:
        user, is_new_user, token, state_data = await _process_sso_login(code, state, db)

        # Build redirect URL with one-time auth code (token is NOT exposed in URL)
        redirect_to = state_data.get("redirect_to", "/")
        # Prevent open redirect — only allow relative URLs
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = "/"
        separator = "&" if "?" in redirect_to else "?"
        auth_code = generate_auth_code(token)
        redirect_url = f"{redirect_to}{separator}code={auth_code}&is_new_user={is_new_user}"

        return RedirectResponse(url=redirect_url)

    except ValueError as e:
        logger.warning("SSO callback validation error: %s", e)
        raise HTTPException(status_code=400, detail="SSO callback validation failed")
    except Exception as e:
        logger.error("SSO callback error: %s", e)
        raise HTTPException(status_code=500, detail="SSO authentication failed")


@router.post("/sso/token", response_model=SSOTokenResponse)
async def exchange_sso_token(body: SSOCallbackRequest):
    """Exchange one-time SSO authorization code for token."""
    from packages.auth.sso import exchange_auth_code

    token = exchange_auth_code(body.code)
    if token is None:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code")
    return {"token": token}


@router.post("/sso/callback", response_model=SSOLoginResponse)
async def sso_callback_api(body: SSOCallbackRequest, db: Session = Depends(get_db)):
    """API-based SSO callback for SPA clients."""
    try:
        user, is_new_user, token, _ = await _process_sso_login(body.code, body.state, db)

        return SSOLoginResponse(
            success=True,
            data={
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role.value if hasattr(user.role, "value") else str(user.role),
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if hasattr(user.created_at, "isoformat") else str(user.created_at),
                    "auth_method": user.auth_method.value if hasattr(user, "auth_method") and hasattr(user.auth_method, "value") else "local",
                },
                "is_new_user": is_new_user,
            },
        )
    except ValueError as e:
        logger.warning("SSO API callback validation error: %s", e)
        raise HTTPException(status_code=400, detail="SSO callback validation failed")
    except Exception as e:
        logger.error("SSO callback API error: %s", e)
        raise HTTPException(status_code=500, detail="SSO authentication failed")
