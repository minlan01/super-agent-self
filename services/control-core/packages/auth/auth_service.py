"""Token creation and verification using HMAC-SHA256."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
import uuid

import structlog

from packages.config import get_settings

logger = structlog.get_logger()


def _get_secret_key() -> str:
    """Read the current SECRET_KEY from settings."""
    return get_settings().security.secret_key


def _get_expire_minutes() -> int:
    """Read token expiry from settings."""
    return get_settings().security.token_expire_minutes


def create_access_token(data: dict, expires_delta: int | None = None) -> str:
    """Create a signed token.

    Format: base64url(json_payload) + "." + hmac_signature
    The payload includes ``exp`` (expiry), ``iat`` (issued-at),
    and ``jti`` (unique token ID) fields.
    """
    payload = data.copy()
    expire_minutes = expires_delta or _get_expire_minutes()
    now = int(time.time())
    payload["exp"] = now + expire_minutes * 60
    payload["iat"] = now
    payload["jti"] = uuid.uuid4().hex

    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("utf-8")

    secret = _get_secret_key()
    signature = hmac.HMAC(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{payload_b64}.{signature}"


def verify_token(token: str) -> dict | None:
    """Verify a token and return its payload, or None if invalid/expired."""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None

        payload_b64, signature = parts

        # Verify signature BEFORE decoding payload
        secret = _get_secret_key()
        expected = hmac.HMAC(
            secret.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            return None

        # Now safe to decode payload — add back padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64_padded = payload_b64 + "=" * padding
        else:
            payload_b64_padded = payload_b64

        payload_bytes = base64.urlsafe_b64decode(payload_b64_padded)
        payload = json.loads(payload_bytes)

        # Check expiry
        exp = payload.get("exp")
        if exp is not None and time.time() > exp:
            return None

        return payload

    except (json.JSONDecodeError, ValueError, binascii.Error):
        logger.warning("Token verification failed: invalid or malformed token")
        return None
