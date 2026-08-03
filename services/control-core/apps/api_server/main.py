"""FastAPI application — Controlled Agent Platform."""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api_server.dependencies import _resolve_current_user, require_permission
from packages.agent_core.schemas import HealthResponse
from packages.agent_core.version import __version__
from packages.config import get_settings
from packages.db.session import (
    Base,  # noqa: F401 — kept for re-export; migrations handled by Alembic
)
from packages.middleware.prometheus import PrometheusMiddleware
from packages.middleware.rate_limiter import RateLimiter
from packages.observability.structured_logger import setup_logging

logger = logging.getLogger(__name__)

# Load settings and initialize structured logging
_settings = get_settings()
setup_logging(level=_settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate configuration
    logger.info("Starting %s v%s (edition=%s)", _settings.app_name, __version__, _settings.edition)

    # In production (non-debug, non-test), reject default secret key
    if (
        not _settings.debug
        and os.getenv("TESTING") != "1"
        and _settings.security.secret_key == "change-me-in-production"
    ):
        raise SystemExit(
            "FATAL: SECRET_KEY must be set via environment variable in production. "
            "Set SECRET_KEY to a cryptographically random string (e.g. `openssl rand -hex 32`)."
        )
    if not _settings.security.require_auth and not _settings.debug and os.getenv("TESTING") != "1":
        logger.warning(
            "SECURITY: REQUIRE_AUTH is False in non-debug mode. "
            "All endpoints are publicly accessible!"
        )

    # Validate all secrets at startup
    try:
        from packages.auth.secrets import validate_secrets_config
        secret_warnings = validate_secrets_config()
        for w in secret_warnings:
            logger.warning("SECRETS: %s", w)
    except Exception as e:
        logger.error("Secrets validation failed: %s", e)
    db_type = "sqlite" if "sqlite" in _settings.database.url else "postgresql"
    logger.info("Database URL: %s", db_type)

    # Ensure workspace directories exist
    from pathlib import Path
    for subdir in ("outputs", "screenshots", "raw"):
        ws_dir = Path(_settings.workspace_root) / subdir
        ws_dir.mkdir(parents=True, exist_ok=True)

    # NOTE: Database schema is managed by Alembic migrations in production.
    # Run `alembic upgrade head` before starting the server.
    # For TEST mode only: use create_all() so in-memory test DBs have tables.
    if os.getenv("TESTING") == "1":
        from packages.db.session import engine
        Base.metadata.create_all(bind=engine)

    # Seed builtin task templates
    from apps.api_server.routes.templates import seed_builtin_templates
    from packages.db.session import SessionLocal
    with SessionLocal() as _seed_db:
        try:
            seed_builtin_templates(_seed_db)
            _seed_db.commit()
            logger.info("Builtin templates seeded")

            try:
                from packages.auth.rbac import get_rbac_service
                rbac = get_rbac_service()
                rbac.seed_if_empty(_seed_db)
                _seed_db.commit()
            except Exception as e:
                logger.error("RBAC seed failed: %s", e)
        except Exception as exc:
            logger.warning("Failed to seed builtin templates: %s", exc)

    # Optional: configure Redis backends for multi-process support
    try:
        cache_yaml = Path("configs/cache.yaml")
        if cache_yaml.exists():
            with open(cache_yaml, encoding="utf-8") as _cache_f:
                cache_cfg = yaml.safe_load(_cache_f)
            if cache_cfg and cache_cfg.get("cache", {}).get("backend") == "redis":
                import redis as redis_lib
                redis_url = cache_cfg["cache"].get("redis_url", "redis://localhost:6379/0")
                sync_redis = redis_lib.from_url(redis_url, decode_responses=True)
                logger.info("Redis backend detected, configuring shared stores")
                from packages.policy.capability_token import configure_nonce_store, _RedisNonceStore
                configure_nonce_store(_RedisNonceStore(sync_redis))
                from packages.auth.sso import get_sso_service, _RedisStateBackend
                sso = await get_sso_service()
                sso._state_backend = _RedisStateBackend(sync_redis)
                from packages.auth.rbac import get_rbac_service, _RedisPermissionCache
                rbac = get_rbac_service()
                rbac.configure_cache_backend(sync_redis)
    except Exception as e:
        logger.info("Redis shared stores not configured (using in-memory): %s", e)

    yield

    # ── Graceful shutdown ─────────────────────────────────────────────────
    logger.info("Shutting down gracefully...")

    try:
        from packages.llm_gateway.provider_router import get_module_router
        router = get_module_router()
        if router is not None:
            from packages.db.session import SessionLocal
            with SessionLocal() as _flush_db:
                try:
                    router.cost_tracker.flush_to_db(_flush_db)
                    _flush_db.commit()
                    logger.info("Cost records flushed to DB on shutdown")
                except Exception as e:
                    logger.warning("Failed to flush cost records on shutdown: %s", e)
            try:
                await router.close()
                logger.info("LLM providers closed")
            except Exception as e:
                logger.warning("Failed to close LLM providers on shutdown: %s", e)
    except Exception as e:
        logger.warning("Cost flush on shutdown failed: %s", e)

    try:
        from packages.cron.scheduler import get_scheduler
        scheduler = get_scheduler()
        if scheduler is not None:
            scheduler.stop()
            logger.info("Cron scheduler stopped")
    except Exception as e:
        logger.warning("Cron scheduler stop failed: %s", e)

    try:
        from packages.mcp.mcp_client import get_mcp_client
        mcp = get_mcp_client()
        if mcp is not None and mcp._connected:
            await mcp.disconnect()
            logger.info("MCP client disconnected")
    except Exception as e:
        logger.warning("MCP disconnect on shutdown failed: %s", e)

    try:
        from packages.executor.tools.browser_tools import _close_browser
        await _close_browser()
        logger.info("Browser closed")
    except Exception as e:
        logger.warning("Browser close on shutdown failed: %s", e)

    try:
        from packages.vision.vision_service import _vision_client
        if _vision_client is not None and not _vision_client.is_closed:
            await _vision_client.aclose()
            logger.info("Vision HTTP client closed")
    except Exception as e:
        logger.warning("Vision client close on shutdown failed: %s", e)

    try:
        from packages.auth.sso import _sso_http_client
        if _sso_http_client is not None and not _sso_http_client.is_closed:
            await _sso_http_client.aclose()
            logger.info("SSO HTTP client closed")
    except Exception as e:
        logger.warning("SSO client close on shutdown failed: %s", e)

    try:
        from packages.executor.tools.web_search_tool import _websearch_client
        if _websearch_client is not None and not _websearch_client.is_closed:
            await _websearch_client.aclose()
            logger.info("WebSearch HTTP client closed")
    except Exception as e:
        logger.warning("WebSearch client close on shutdown failed: %s", e)

    try:
        from apps.api_server.routes.webhooks import get_messaging_router
        msg_router = get_messaging_router()
        for name, provider in msg_router.providers.items():
            try:
                await provider.close()
            except Exception as e:
                logger.warning("Failed to close messaging provider '%s': %s", name, e)
        logger.info("Messaging providers closed")
    except Exception as e:
        logger.warning("Messaging providers close on shutdown failed: %s", e)

    try:
        from packages.db.session import engine
        engine.dispose()
        logger.info("Database engine disposed")
    except Exception as e:
        logger.warning("Database engine dispose on shutdown failed: %s", e)

    logger.info("Graceful shutdown complete")


_is_production = os.getenv("ENVIRONMENT", "development") == "production"

_OPENAPI_TAGS = [
    {"name": "health", "description": "Health check and readiness probes"},
    {"name": "tasks", "description": "Task lifecycle management — create, plan, execute, cancel"},
    {"name": "memory", "description": "Long-term memory storage and retrieval"},
    {"name": "skills", "description": "Skill extraction, validation, and reuse"},
    {"name": "audit", "description": "Audit trail for all agent actions"},
    {"name": "approvals", "description": "Approval workflow for skills and actions"},
    {"name": "export", "description": "Data export in JSON and CSV formats"},
    {"name": "files", "description": "File download with path traversal protection"},
    {"name": "personal", "description": "Personal edition features"},
    {"name": "editions", "description": "Edition profile management"},
    {"name": "chat", "description": "Conversational agent interface"},
    {"name": "conversations", "description": "Conversation history management"},
    {"name": "auth", "description": "User authentication and token management"},
    {"name": "cron", "description": "Cron job scheduling and management"},
    {"name": "admin", "description": "Admin operations — backup, restore, rate limits"},
    {"name": "notifications", "description": "Real-time notification management"},
    {"name": "analytics", "description": "Analytics and reporting dashboard"},
    {"name": "metrics", "description": "Prometheus-compatible metrics"},
    {"name": "search", "description": "Unified search across entities"},
    {"name": "templates", "description": "Task template management"},
    {"name": "graphql", "description": "GraphQL query interface"},
    {"name": "voice", "description": "Voice input/output (Phase 3)"},
    {"name": "desktop", "description": "Desktop automation — file system, windows, screenshots"},
    {"name": "webhooks", "description": "Inbound webhook handling from messaging platforms"},
    {"name": "messaging", "description": "Outbound messaging and channel management"},
    {
        "name": "marketplace",
        "description": (
            "Skill marketplace — browse, subscribe, rate, and promote skills"
        ),
    },
]

app = FastAPI(
    title="Controlled Agent Platform",
    version=__version__,
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
    openapi_tags=_OPENAPI_TAGS,
)


# ── Request logging middleware ─────────────────────────────────────────────


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status code, duration, and request ID.

    Binds ``request_id`` and ``path`` into structlog contextvars so that all
    downstream loggers (route handlers, services, repositories) automatically
    inherit the request correlation id without explicit plumbing.
    """

    async def dispatch(self, request, call_next):
        import structlog

        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s → %d (%.1fms) req=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Add Cache-Control headers for read-only API paths."""

    CACHE_RULES = [
        ("/api/v1/marketplace", "public, max-age=60"),
        ("/api/v1/templates", "private, max-age=30"),
        ("/api/v1/rbac", "private, max-age=120"),
        ("/api/v1/skills", "private, max-age=30"),
        ("/api/v1/health", "no-cache"),
    ]

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.method == "GET" and response.status_code == 200:
            for prefix, cache_value in self.CACHE_RULES:
                if request.url.path.startswith(prefix):
                    response.headers["Cache-Control"] = cache_value
                    break
        return response


app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CacheControlMiddleware)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


_MAX_REQUEST_BODY = 10 * 1024 * 1024


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with Content-Length exceeding the limit."""

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_REQUEST_BODY:
            return JSONResponse(
                status_code=413,
                content={"success": False, "message": "Request body too large"},
            )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestBodyLimitMiddleware)


# ── Prometheus Metrics ──────────────────────────────────────────────────────

app.add_middleware(PrometheusMiddleware)


# ── Rate Limiting ────────────────────────────────────────────────────────────

if not os.getenv("TESTING"):
    # Load per-route rate limits from YAML config
    _rate_limits_path = Path("configs/rate_limits.yaml")
    _route_limits: dict[str, tuple[int, int]] = {}
    _rl_default = (60, 60)
    if _rate_limits_path.exists():
        try:
            _rl_cfg = yaml.safe_load(_rate_limits_path.read_text(encoding="utf-8")) or {}
            _rl_section = _rl_cfg.get("rate_limits", {})
            _rl_default_cfg = _rl_section.get("default", {})
            _rl_default = (
                _rl_default_cfg.get("max_requests", 60),
                _rl_default_cfg.get("window_seconds", 60),
            )
            for _prefix, _cfg in _rl_section.get("routes", {}).items():
                _route_limits[_prefix] = (
                    _cfg.get("max_requests", 60),
                    _cfg.get("window_seconds", 60),
                )
        except Exception as e:
            logger.warning("Failed to load rate limits config from %s: %s", _rate_limits_path, e)
    app.add_middleware(
        RateLimiter,
        max_requests=_rl_default[0],
        window_seconds=_rl_default[1],
        route_limits=_route_limits,
        config_path=str(_rate_limits_path),
    )

# ── CORS ─────────────────────────────────────────────────────────────────────

_cors_config = {}
_config_path = Path("configs/app.yaml")
if _config_path.exists():
    try:
        _cfg = yaml.safe_load(_config_path.read_text(encoding="utf-8")) or {}
        _cors_config = _cfg.get("cors", {})
    except Exception as e:
        logger.warning("Failed to load CORS config from %s: %s", _config_path, e)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_config.get("allow_origins", ["http://localhost:5173", "http://localhost:8000"]),
    allow_credentials=_cors_config.get("allow_credentials", True),
    allow_methods=_cors_config.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
    allow_headers=_cors_config.get("allow_headers", [
        "Authorization", "Content-Type", "X-Request-ID", "Accept",
    ]),
)


# ── Health ───────────────────────────────────────────────────────────────────


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Health check",
    description="Lightweight liveness probe returning service status, version, and edition.",
)
def health_check() -> HealthResponse:
    return HealthResponse()


from apps.api_server.routes.health import router as health_router  # noqa: E402

app.include_router(health_router, prefix="/api/v1/health", tags=["health"])


# ── Prometheus Metrics ──────────────────────────────────────────────────────

from apps.api_server.routes.metrics import router as metrics_router  # noqa: E402

app.include_router(metrics_router, prefix="/api/v1/metrics", tags=["metrics"])


# ── Global exception handlers ─────────────────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Normalize 422 validation errors to ``ErrorResponse`` shape."""
    errors = exc.errors()
    msg = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in errors)
    request_id = request.headers.get("X-Request-ID")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error_code": "validation_error",
            "message": msg,
            "request_id": request_id,
            "details": {"errors": errors},
        },
        headers={"X-Request-ID": request_id} if request_id else {},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalize HTTPException responses to ``ErrorResponse`` shape."""
    request_id = request.headers.get("X-Request-ID")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": f"http_{exc.status_code}",
            "message": detail,
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id} if request_id else {},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — never leak ``str(exc)`` to clients."""
    request_id = request.headers.get("X-Request-ID")
    # exc_info=True ensures the structlog ExceptionRenderer includes the full traceback.
    logger.exception(
        "Unhandled exception on %s %s (req=%s)",
        request.method, request.url.path, request_id,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "internal_error",
            "message": "Internal server error. Please try again later.",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id} if request_id else {},
    )


# ── Routers ──────────────────────────────────────────────────────────────────

import importlib

_ROUTE_REGISTRY: list[tuple[str, str, list[str]]] = [
    ("tasks", "/api/v1/tasks", ["tasks"]),
    ("memory", "/api/v1/memory", ["memory"]),
    ("skills", "/api/v1/skills", ["skills"]),
    ("audit", "/api/v1/audit", ["audit"]),
    ("approvals", "/api/v1/approvals", ["approvals"]),
    ("gateway_approvals", "/api/v1/gateway-approvals", ["gateway-approvals"]),
    ("export", "/api/v1/export", ["export"]),
    ("files", "/api/v1/files", ["files"]),
    ("personal", "/api/v1/personal", ["personal"]),
    ("editions", "/api/v1/editions", ["editions"]),
    ("chat", "/api/v1/chat", ["chat"]),
    ("conversations", "/api/v1/conversations", ["conversations"]),
    ("auth", "/api/v1/auth", ["auth"]),
    ("voice", "/api/v1/voice", ["voice"]),
    ("vision", "/api/v1/vision", ["vision"]),
    ("desktop", "/api/v1/desktop", ["desktop"]),
    ("agents", "/api/v1/agents", ["agents"]),
    ("plugins", "/api/v1/plugins", ["plugins"]),
    ("cron", "/api/v1/cron", ["cron"]),
    ("admin", "/api/v1/admin", ["admin"]),
    ("rbac", "/api/v1/rbac", ["RBAC"]),
    ("notifications", "/api/v1/notifications", ["notifications"]),
    ("analytics", "/api/v1/analytics", ["analytics"]),
    ("search", "/api/v1/search", ["search"]),
    ("task_dependencies", "/api/v1/tasks", ["task-dependencies"]),
    ("templates", "/api/v1/templates", ["templates"]),
    ("webhooks", "/api/v1", ["webhooks", "messaging"]),
    ("marketplace", "/api/v1/marketplace", ["marketplace"]),
]

for module_name, prefix, tags in _ROUTE_REGISTRY:
    mod = importlib.import_module(f"apps.api_server.routes.{module_name}")
    app.include_router(mod.router, prefix=prefix, tags=tags)

from apps.api_server.routes.ws import router as ws_router  # noqa: E402

app.include_router(ws_router)


# ── GraphQL ────────────────────────────────────────────────────────────────

from strawberry.fastapi import GraphQLRouter  # noqa: E402

from packages.db.session import get_db as _get_graphql_db  # noqa: E402
from packages.graphql.schema import schema  # noqa: E402


async def _graphql_context(
    db=Depends(_get_graphql_db),
    user=Depends(_resolve_current_user),
):
    return {"db": db, "user": user}


graphql_app = GraphQLRouter(
    schema,
    context_getter=_graphql_context,
)
app.include_router(graphql_app, prefix="/api/v1/graphql", tags=["graphql"])
