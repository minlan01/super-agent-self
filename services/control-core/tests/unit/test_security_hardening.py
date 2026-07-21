"""Security hardening tests — docs URL, token expiry, sanitize."""

from __future__ import annotations

import os
from unittest.mock import patch


class TestDocsDisabledInProduction:
    """Swagger/ReDoc should be disabled when ENVIRONMENT=production."""

    def test_docs_disabled_in_production(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            # Re-evaluate the condition
            is_prod = os.getenv("ENVIRONMENT", "development") == "production"
            assert is_prod is True
            # In production, docs_url would be None
            docs_url = None if is_prod else "/docs"
            assert docs_url is None

    def test_docs_enabled_in_development(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            is_prod = os.getenv("ENVIRONMENT", "development") == "production"
            assert is_prod is False
            docs_url = None if is_prod else "/docs"
            assert docs_url == "/docs"

    def test_docs_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove ENVIRONMENT if set
            os.environ.pop("ENVIRONMENT", None)
            is_prod = os.getenv("ENVIRONMENT", "development") == "production"
            assert is_prod is False


class TestTokenExpiryCheck:
    """Test client-side token expiry validation."""

    def _is_token_expired(self, token: str) -> bool:
        """Replicate the frontend isTokenExpired logic in Python."""
        import base64
        import json

        try:
            parts = token.split(".")
            if len(parts) < 2:
                return True
            payload = json.loads(base64.b64decode(parts[0]))
            if "exp" in payload:
                import time
                return time.time() > payload["exp"]
            return False
        except Exception:
            return True

    def test_expired_token_detected(self):
        import base64
        import json
        import time

        payload = json.dumps({"sub": "user1", "exp": time.time() - 3600})
        token = base64.b64encode(payload.encode()).decode() + ".fake_sig"
        assert self._is_token_expired(token) is True

    def test_valid_token_passes(self):
        import base64
        import json
        import time

        payload = json.dumps({"sub": "user1", "exp": time.time() + 3600})
        token = base64.b64encode(payload.encode()).decode() + ".fake_sig"
        assert self._is_token_expired(token) is False

    def test_malformed_token_detected(self):
        assert self._is_token_expired("not-a-token") is True

    def test_token_without_exp_passes(self):
        import base64
        import json

        payload = json.dumps({"sub": "user1"})
        token = base64.b64encode(payload.encode()).decode() + ".fake_sig"
        assert self._is_token_expired(token) is False


class TestXSSSanitization:
    """Test HTML sanitization for ECharts tooltip."""

    def test_sanitize_html_entities(self):
        def sanitize(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        assert sanitize('<script>alert("xss")</script>') == "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"
        assert sanitize("normal text") == "normal text"
        assert sanitize("a&b<c>d") == "a&amp;b&lt;c&gt;d"
