"""SSRF Protection — validates outbound URLs against internal network access.

Prevents Server-Side Request Forgery by blocking requests to:
- Loopback addresses (127.0.0.0/8, ::1, localhost)
- Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Link-local addresses (169.254.0.0/16, fe80::/10)
- Cloud metadata endpoints (169.254.169.254)
- Hostname-based internal access (localhost, *.local, *.internal)
- DNS rebinding via IP resolution (optional, when socket is available)

Used by browser tools, web search, MCP HTTP connections, and any
outbound HTTP request made on behalf of a user.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_METADATA_IP = ipaddress.ip_address("169.254.169.254")

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}

_BLOCKED_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
    ".test",
    ".example",
    ".invalid",
    ".onion",
)

_ALLOWED_SCHEMES = {"http", "https"}
_BROWSER_SAFE_SCHEMES = {"about"}


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if addr == _METADATA_IP:
        return True
    return any(addr in net for net in _PRIVATE_NETWORKS)


def _is_blocked_hostname(hostname: str) -> bool:
    lower = hostname.lower()
    if lower in _BLOCKED_HOSTNAMES:
        return True
    for suffix in _BLOCKED_SUFFIXES:
        if lower.endswith(suffix) or lower == suffix[1:]:
            return True
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", lower):
        try:
            if _is_private_ip(lower):
                return True
        except ValueError:
            pass
    return False


def validate_url(url: str, *, resolve_dns: bool = True) -> tuple[bool, str]:
    """Validate a URL for SSRF safety.

    Args:
        url: The URL to validate.
        resolve_dns: If True, resolve the hostname and check the IP.
            Set to False when DNS resolution is not desired (e.g. offline).

    Returns:
        (is_safe, reason) — is_safe is True if the URL is allowed.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        logger.warning("URL parsing failed for SSRF check: %s — %s", url[:80], e)
        return False, "Invalid URL format"

    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        if scheme in _BROWSER_SAFE_SCHEMES and parsed.netloc == "" and parsed.path in ("blank", "srcdoc"):
            return True, "ok"
        return False, f"Blocked scheme: {scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname in URL"

    if _is_blocked_hostname(hostname):
        return False, f"Blocked hostname: {hostname}"

    if resolve_dns:
        try:
            addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as e:
            logger.warning("DNS resolution failed for SSRF check on hostname '%s': %s", hostname, e)
            return False, f"DNS resolution failed for hostname '{hostname}': {e}"
        except Exception as e:
            logger.warning("DNS lookup error for SSRF check on hostname '%s': %s", hostname, e)
            return False, f"DNS lookup error for hostname '{hostname}': {e}"

        for family, _type, _proto, _canon, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                return False, f"Resolved to private IP: {ip_str} for hostname {hostname}"

    return True, "ok"


def validate_url_fast(url: str) -> tuple[bool, str]:
    """Fast SSRF check without DNS resolution.

    Use this for high-frequency checks where DNS resolution would be
    too slow. Falls back to hostname-based checks only.
    """
    return validate_url(url, resolve_dns=False)
