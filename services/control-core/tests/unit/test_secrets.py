"""Tests for Secrets Manager — secure loading and validation of API keys."""

from __future__ import annotations

import pytest

from packages.auth.secrets import (
    is_placeholder,
    load_secret,
    mask_secret,
    validate_secrets_config,
)


class TestMaskSecret:
    def test_normal_secret(self):
        assert mask_secret("sk-abc123xyz789") == "sk-a***********"

    def test_short_secret(self):
        assert mask_secret("sk") == "**"

    def test_exact_visible_chars(self):
        assert mask_secret("sk-a", visible_chars=4) == "****"

    def test_custom_visible_chars(self):
        result = mask_secret("sk-abc123xyz789", visible_chars=6)
        assert result.startswith("sk-abc")
        assert "*" in result


class TestIsPlaceholder:
    def test_change_me(self):
        assert is_placeholder("change-me-in-production") is True

    def test_change_underscore(self):
        assert is_placeholder("change_me") is True

    def test_your_api_key(self):
        assert is_placeholder("your-api-key-here") is True

    def test_xxx_placeholder(self):
        assert is_placeholder("xxxxxxxxxxxx") is True

    def test_bracket_placeholder(self):
        assert is_placeholder("<your-key>") is True

    def test_square_bracket_placeholder(self):
        assert is_placeholder("[API_KEY]") is True

    def test_real_key(self):
        assert is_placeholder("sk-abc123def456ghi789") is False

    def test_empty_string(self):
        assert is_placeholder("") is True

    def test_too_short(self):
        assert is_placeholder("abc") is True

    def test_test_key(self):
        assert is_placeholder("test-key-123") is True


class TestLoadSecret:
    def test_load_from_env(self, monkeypatch):
        monkeypatch.setenv("TEST_SECRET_KEY", "sk-real-key-12345")
        result = load_secret("TEST_SECRET_KEY")
        assert result == "sk-real-key-12345"

    def test_load_default(self):
        result = load_secret("NONEXISTENT_SECRET_XYZ", default="fallback")
        assert result == "fallback"

    def test_required_missing_raises(self):
        with pytest.raises(ValueError, match="Required secret"):
            load_secret("NONEXISTENT_SECRET_XYZ", required=True)

    def test_required_placeholder_raises(self, monkeypatch):
        monkeypatch.setenv("TEST_PLACEHOLDER_KEY", "change-me-now")
        with pytest.raises(ValueError, match="placeholder"):
            load_secret("TEST_PLACEHOLDER_KEY", required=True)

    def test_placeholder_warning(self, monkeypatch):
        result = load_secret("TEST_WARN_KEY", default="change-me-default")
        assert result == "change-me-default"


class TestValidateSecretsConfig:
    def test_default_secret_key_warning(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        warnings = validate_secrets_config()
        assert any("SECRET_KEY" in w for w in warnings)

    def test_placeholder_api_key_warning(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "your-api-key-here")
        warnings = validate_secrets_config()
        assert any("DeepSeek" in w for w in warnings)

    def test_no_warnings_with_real_keys(self, monkeypatch):
        monkeypatch.setenv(
            "SECRET_KEY",
            "a-real-secret-key-that-is-long-enough-1234567890",
        )
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        warnings = validate_secrets_config()
        assert len(warnings) == 0
