"""Centralized configuration — loads from env vars and YAML config."""

from __future__ import annotations

import functools
import logging
import os
import re
import warnings
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

from packages.agent_core.version import __version__


class DatabaseSettings(BaseSettings):
    url: str = "sqlite:///./data/agent_platform.db"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle: int = 3600
    pool_pre_ping: bool = True

    model_config = {"env_prefix": "database_"}

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not re.match(r"^(sqlite|postgresql|mysql|postgres)://", v):
            raise ValueError(
                "database.url must start with a supported scheme "
                "(sqlite://, postgresql://, mysql://, postgres://)"
            )
        return v


class SecuritySettings(BaseSettings):
    secret_key: str = "change-me-in-production"
    token_expire_minutes: int = 60
    capability_token_expire_minutes: int = 5
    require_auth: bool = True

    model_config = {"env_prefix": "security_"}

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        if v == "change-me-in-production":
            return v
        if len(v) < 32:
            raise ValueError(
                "security.secret_key must be at least 32 characters long. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v


class Settings(BaseSettings):
    """Top-level settings — loads from env vars with YAML fallback."""

    app_name: str = "Controlled Agent Platform"
    version: str = __version__
    edition: str = "enterprise"
    debug: bool = False
    log_level: str = "INFO"

    database: DatabaseSettings = DatabaseSettings()
    security: SecuritySettings = SecuritySettings()

    workspace_root: str = "./workspace"
    max_file_size_mb: int = 50

    model_config = {"env_prefix": "app_"}


def _load_yaml_config() -> dict:
    """Load configs/app.yaml if it exists."""
    config_path = Path("configs/app.yaml")
    if not config_path.exists():
        return {}
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Failed to load YAML config from %s: %s", config_path, e)
        return {}


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Create Settings with YAML defaults overlaid by env vars (cached)."""
    yaml_cfg = _load_yaml_config()
    app_cfg = yaml_cfg.get("app", {})
    db_cfg = yaml_cfg.get("database", {})
    sec_cfg = yaml_cfg.get("security", {})
    ws_cfg = yaml_cfg.get("workspace", {})

    # Override DATABASE_URL from environment if present
    db_url = os.getenv("DATABASE_URL", db_cfg.get("url", "sqlite:///./data/agent_platform.db"))

    settings = Settings(
        app_name=app_cfg.get("name", "Controlled Agent Platform"),
        version=app_cfg.get("version", __version__),
        edition=app_cfg.get("edition", "enterprise"),
        debug=app_cfg.get("debug", False),
        log_level=app_cfg.get("log_level", "INFO"),
        database=DatabaseSettings(
            url=db_url,
            echo=db_cfg.get("echo", False),
            pool_size=int(db_cfg.get("pool_size", 5)),
            max_overflow=int(db_cfg.get("max_overflow", 10)),
            pool_recycle=int(db_cfg.get("pool_recycle", 3600)),
            pool_pre_ping=db_cfg.get("pool_pre_ping", True),
        ),
        security=SecuritySettings(
            secret_key=os.getenv(
                "SECRET_KEY",
                sec_cfg.get("secret_key", "change-me-in-production"),
            ),
            token_expire_minutes=int(os.getenv(
                "TOKEN_EXPIRE_MINUTES",
                sec_cfg.get("token_expire_minutes", 60),
            )),
            require_auth=os.getenv(
                "REQUIRE_AUTH",
                str(sec_cfg.get("require_auth", True)),
            ).lower() in ("1", "true", "yes"),
        ),
        workspace_root=ws_cfg.get("root", "./workspace"),
        max_file_size_mb=ws_cfg.get("max_file_size_mb", 50),
    )

    # Warn on insecure defaults in production mode
    if not settings.debug and settings.security.secret_key == "change-me-in-production":
        warnings.warn(
            "SECRET_KEY is set to the default value. Change it in production!",
            stacklevel=2,
        )
    if not settings.security.require_auth and not settings.debug:
        warnings.warn(
            "REQUIRE_AUTH is False. All API endpoints are publicly accessible!",
            stacklevel=2,
        )

    return settings


def clear_settings_cache() -> None:
    """Clear the settings cache (useful for tests)."""
    get_settings.cache_clear()
