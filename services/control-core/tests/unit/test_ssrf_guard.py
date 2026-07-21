"""Tests for SSRF Guard — URL validation against internal network access."""

from __future__ import annotations

from packages.policy.ssrf_guard import (
    _is_blocked_hostname,
    _is_private_ip,
    validate_url,
    validate_url_fast,
)


class TestPrivateIPDetection:
    def test_loopback_ipv4(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_loopback_ipv6(self):
        assert _is_private_ip("::1") is True

    def test_class_a_private(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_class_b_private(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_class_c_private(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_link_local(self):
        assert _is_private_ip("169.254.1.1") is True

    def test_cloud_metadata(self):
        assert _is_private_ip("169.254.169.254") is True

    def test_public_ip(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_another_public_ip(self):
        assert _is_private_ip("1.1.1.1") is False

    def test_invalid_ip(self):
        assert _is_private_ip("not-an-ip") is False

    def test_ipv6_unique_local(self):
        assert _is_private_ip("fc00::1") is True

    def test_ipv6_link_local(self):
        assert _is_private_ip("fe80::1") is True


class TestBlockedHostname:
    def test_localhost(self):
        assert _is_blocked_hostname("localhost") is True

    def test_localhost_localdomain(self):
        assert _is_blocked_hostname("localhost.localdomain") is True

    def test_local_suffix(self):
        assert _is_blocked_hostname("myhost.local") is True

    def test_internal_suffix(self):
        assert _is_blocked_hostname("myhost.internal") is True

    def test_onion_suffix(self):
        assert _is_blocked_hostname("example.onion") is True

    def test_normal_hostname(self):
        assert _is_blocked_hostname("example.com") is False

    def test_ip_hostname_private(self):
        assert _is_blocked_hostname("192.168.1.1") is True

    def test_ip_hostname_public(self):
        assert _is_blocked_hostname("8.8.8.8") is False


class TestValidateUrlFast:
    def test_http_allowed(self):
        ok, reason = validate_url_fast("http://example.com/path")
        assert ok is True
        assert reason == "ok"

    def test_https_allowed(self):
        ok, reason = validate_url_fast("https://example.com/path")
        assert ok is True
        assert reason == "ok"

    def test_ftp_blocked(self):
        ok, reason = validate_url_fast("ftp://example.com/file")
        assert ok is False
        assert "Blocked scheme" in reason

    def test_file_scheme_blocked(self):
        ok, reason = validate_url_fast("file:///etc/passwd")
        assert ok is False

    def test_localhost_blocked(self):
        ok, reason = validate_url_fast("http://localhost:8080/api")
        assert ok is False
        assert "Blocked hostname" in reason

    def test_127_ip_blocked(self):
        ok, reason = validate_url_fast("http://127.0.0.1:8080/api")
        assert ok is False

    def test_private_ip_blocked(self):
        ok, reason = validate_url_fast("http://192.168.1.1/admin")
        assert ok is False

    def test_10_ip_blocked(self):
        ok, reason = validate_url_fast("http://10.0.0.1/internal")
        assert ok is False

    def test_cloud_metadata_blocked(self):
        ok, reason = validate_url_fast("http://169.254.169.254/latest/meta-data/")
        assert ok is False

    def test_public_domain_allowed(self):
        ok, reason = validate_url_fast("https://api.openai.com/v1/chat")
        assert ok is True

    def test_no_hostname_blocked(self):
        ok, reason = validate_url_fast("http:///path")
        assert ok is False

    def test_internal_suffix_blocked(self):
        ok, reason = validate_url_fast("https://myhost.internal/api")
        assert ok is False

    def test_local_suffix_blocked(self):
        ok, reason = validate_url_fast("https://myhost.local/api")
        assert ok is False


class TestValidateUrlWithDNS:
    def test_public_domain_ok(self):
        ok, reason = validate_url("https://example.com", resolve_dns=False)
        assert ok is True

    def test_localhost_blocked_without_dns(self):
        ok, reason = validate_url("http://localhost:8080", resolve_dns=True)
        assert ok is False
