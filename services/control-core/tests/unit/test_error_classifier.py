"""Tests for Error Classifier — categorizes errors for smarter retry."""

from __future__ import annotations

from packages.llm_gateway.error_classifier import (
    ErrorCategory,
    classify_error,
)


class TestRateLimitedErrors:
    def test_429_status(self):
        result = classify_error("HTTP 429 Too Many Requests")
        assert result.category == ErrorCategory.RATE_LIMITED
        assert result.should_retry is True

    def test_rate_limit_keyword(self):
        result = classify_error("Rate limit exceeded for API")
        assert result.category == ErrorCategory.RATE_LIMITED
        assert result.should_retry is True

    def test_throttled_keyword(self):
        result = classify_error("Request was throttled")
        assert result.category == ErrorCategory.RATE_LIMITED

    def test_quota_exceeded(self):
        result = classify_error("Quota exceeded for this billing period")
        assert result.category == ErrorCategory.RATE_LIMITED

    def test_explicit_retry_after(self):
        result = classify_error("some error", retry_after=30.0)
        assert result.category == ErrorCategory.RATE_LIMITED
        assert result.retry_after == 30.0
        assert result.suggested_delay == 30.0


class TestTimeoutErrors:
    def test_timeout_keyword(self):
        result = classify_error("Request timed out after 30s")
        assert result.category == ErrorCategory.TIMEOUT
        assert result.should_retry is True

    def test_deadline_exceeded(self):
        result = classify_error("Deadline exceeded")
        assert result.category == ErrorCategory.TIMEOUT

    def test_asyncio_timeout_error(self):
        result = classify_error(TimeoutError("Connection timed out"))
        assert result.category == ErrorCategory.TIMEOUT


class TestNetworkErrors:
    def test_connection_refused(self):
        result = classify_error("Connection refused by remote host")
        assert result.category == ErrorCategory.NETWORK
        assert result.should_retry is True

    def test_dns_resolution_failure(self):
        result = classify_error("Could not resolve hostname")
        assert result.category == ErrorCategory.NETWORK

    def test_network_unreachable(self):
        result = classify_error("Network is unreachable")
        assert result.category == ErrorCategory.NETWORK


class TestPermanentErrors:
    def test_401_unauthorized(self):
        result = classify_error("HTTP 401 Unauthorized")
        assert result.category == ErrorCategory.PERMANENT
        assert result.should_retry is False

    def test_403_forbidden(self):
        result = classify_error("HTTP 403 Forbidden")
        assert result.category == ErrorCategory.PERMANENT
        assert result.should_retry is False

    def test_404_not_found(self):
        result = classify_error("HTTP 404 Not Found")
        assert result.category == ErrorCategory.PERMANENT

    def test_invalid_api_key(self):
        result = classify_error("Invalid API key provided")
        assert result.category == ErrorCategory.PERMANENT
        assert result.should_retry is False

    def test_permission_denied(self):
        result = classify_error("Permission denied for resource")
        assert result.category == ErrorCategory.PERMANENT

    def test_422_unprocessable(self):
        result = classify_error("HTTP 422 Unprocessable Entity")
        assert result.category == ErrorCategory.PERMANENT


class TestTransientErrors:
    def test_500_server_error(self):
        result = classify_error("HTTP 500 Internal Server Error")
        assert result.category == ErrorCategory.TRANSIENT
        assert result.should_retry is True

    def test_502_bad_gateway(self):
        result = classify_error("HTTP 502 Bad Gateway")
        assert result.category == ErrorCategory.TRANSIENT

    def test_503_service_unavailable(self):
        result = classify_error("HTTP 503 Service Unavailable")
        assert result.category == ErrorCategory.TRANSIENT

    def test_504_gateway_timeout(self):
        result = classify_error("HTTP 504 Gateway Timeout")
        assert result.category == ErrorCategory.TIMEOUT


class TestUnknownErrors:
    def test_unknown_error(self):
        result = classify_error("Something completely unexpected happened")
        assert result.category == ErrorCategory.UNKNOWN
        assert result.should_retry is False

    def test_exception_object(self):
        result = classify_error(ValueError("bad value"))
        assert result.category in (ErrorCategory.UNKNOWN, ErrorCategory.PERMANENT)


class TestClassifiedErrorToDict:
    def test_to_dict(self):
        result = classify_error("HTTP 429 Rate Limited")
        d = result.to_dict()
        assert "category" in d
        assert "should_retry" in d
        assert "suggested_delay" in d
        assert d["category"] == "rate_limited"
