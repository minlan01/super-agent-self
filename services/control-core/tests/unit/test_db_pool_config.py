"""Tests for database pool configuration wired from config.py into session.py."""

import os
from unittest.mock import patch

from packages.config import DatabaseSettings, Settings, clear_settings_cache, get_settings


class TestBuildEngineUsesConfigSettings:
    """Verify _build_engine reads pool settings from get_settings() for PostgreSQL."""

    def test_postgres_engine_uses_config_pool_settings(self):
        """PostgreSQL engine must receive pool_size, max_overflow, pool_recycle from config."""
        from packages.db.session import _build_engine

        mock_settings = Settings(
            database=DatabaseSettings(
                url="postgresql://user:pass@localhost/testdb",
                echo=False,
                pool_size=7,
                max_overflow=15,
                pool_recycle=1800,
                pool_pre_ping=False,
            ),
        )
        with patch("packages.config.get_settings", return_value=mock_settings):
            engine = _build_engine()

        assert engine.pool.size() == 7
        assert engine.pool._max_overflow == 15
        assert engine.pool._recycle == 1800
        engine.dispose()

    def test_sqlite_engine_no_pool_size_overflow(self):
        """SQLite engine should not apply pool_size/max_overflow (not supported)."""
        from packages.db.session import _build_engine

        mock_settings = Settings(
            database=DatabaseSettings(
                url="sqlite:///./data/test_agent.db",
                echo=False,
                pool_size=7,
                max_overflow=15,
                pool_recycle=1800,
                pool_pre_ping=True,
            ),
        )
        with patch("packages.config.get_settings", return_value=mock_settings):
            engine = _build_engine()

        # SQLite engine should work fine — it ignores pool_size/max_overflow
        assert "sqlite" in str(engine.url)
        engine.dispose()

    def test_config_pool_settings_from_yaml(self):
        """get_settings() should pass pool fields from YAML config."""
        clear_settings_cache()
        with patch("packages.config._load_yaml_config", return_value={
            "database": {
                "url": "postgresql://user:pass@localhost/yamltest",
                "echo": True,
                "pool_size": 12,
                "max_overflow": 20,
                "pool_recycle": 900,
                "pool_pre_ping": False,
            },
        }):
            settings = get_settings()

        assert settings.database.pool_size == 12
        assert settings.database.max_overflow == 20
        assert settings.database.pool_recycle == 900
        assert settings.database.pool_pre_ping is False

    def test_fallback_to_env_vars_on_config_error(self):
        """If get_settings() raises, _build_engine should fall back to env vars."""
        from packages.db.session import _build_engine

        with patch("packages.config.get_settings", side_effect=Exception("config broken")):
            with patch.dict(os.environ, {
                "DATABASE_URL": "postgresql://user:pass@localhost/fallback",
                "DB_POOL_SIZE": "3",
                "DB_MAX_OVERFLOW": "8",
                "DB_POOL_RECYCLE": "600",
            }):
                engine = _build_engine()

        assert engine.pool.size() == 3
        assert engine.pool._max_overflow == 8
        assert engine.pool._recycle == 600
        engine.dispose()

    def test_database_settings_defaults(self):
        """DatabaseSettings defaults should match expected values."""
        ds = DatabaseSettings()
        assert ds.pool_size == 5
        assert ds.max_overflow == 10
        assert ds.pool_recycle == 3600
        assert ds.pool_pre_ping is True

    def test_echo_passed_to_engine(self):
        """Engine echo setting should reflect config."""
        from packages.db.session import _build_engine

        mock_settings = Settings(
            database=DatabaseSettings(
                url="sqlite:///./data/test_echo.db",
                echo=True,
            ),
        )
        with patch("packages.config.get_settings", return_value=mock_settings):
            engine = _build_engine()

        assert engine.echo is True
        engine.dispose()
