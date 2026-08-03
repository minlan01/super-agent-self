"""GrantIssuer — mints opaque CapabilityGrant handles and persists digests.

Spec §4.3 + PROJECT-CONTEXT invariant: the plaintext handle is returned to
the caller; only its SHA-256 digest is stored in the database.  ToolGateway
verifies by recomputing digest(handle) and looking up the row.

State machine: ISSUED -> CONSUMED (after single use) | EXPIRED | REVOKED.
max_uses=1 enforced by atomic conditional UPDATE in GrantRepository.consume().
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from packages.db.models import GrantStatusDB
from packages.db.repositories.grant_repo import GrantRepository

logger = structlog.get_logger()

# Default TTL for a grant (5 minutes, matching GRANT_DEFAULT_TTL_SECONDS).
_DEFAULT_TTL = timedelta(seconds=300)


@dataclass(frozen=True)
class IssuedGrant:
    """Result of GrantIssuer.issue(): the plaintext handle + metadata.

    The caller (executor/approval service) holds *handle* in memory and
    passes it to ToolGateway.  The DB only has *grant_id* + *handle_digest*.
    """
    handle: str          # 256-bit opaque, secrets.token_urlsafe(32)
    grant_id: str        # DB primary key
    handle_digest: str   # SHA-256(handle), also stored in DB
    expires_at: datetime


@dataclass(frozen=True)
class VerifiedGrant:
    """Result of GrantIssuer.verify(): the matched DB row + validity flag."""
    grant_id: str
    step_run_id: str
    tenant_id: str
    bound_args_hash: str
    resource_scope: dict[str, Any]
    risk_level: str
    expires_at: datetime
    valid: bool
    reason: str = ""


class GrantIssuer:
    """Mints and verifies CapabilityGrant handles.

    Responsibilities (PROJECT-CONTEXT §授权与审批不变量):
      - Generate 256-bit opaque handle (secrets.token_urlsafe).
      - Persist only SHA-256(handle) to DB.
      - Bind: tenant/workspace/step_run/tool/args_hash/resource_scope/
        security_context_digest/approval_resolution_id/audience/nonce/
        expires_at/max_uses=1.
      - break_glass key_id exempts approval_resolution_id but must log.
      - Atomic consume: exactly one concurrent caller wins.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _digest(handle: str) -> str:
        """SHA-256 of the plaintext handle, hex-encoded (64 chars)."""
        return hashlib.sha256(handle.encode("utf-8")).hexdigest()

    def issue(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
        tool_name: str,
        bound_args_hash: str,
        risk_level: str,
        resource_scope: dict[str, Any],
        security_context_digest: str,
        approval_resolution_id: str | None = None,
        key_id: str = "default",
        audience: str = "tool_gateway",
        ttl: timedelta | None = None,
    ) -> IssuedGrant:
        """Mint a new opaque grant handle and persist its digest.

        Raises ValueError if a high-risk grant lacks approval_resolution_id
        and key_id is not "break_glass" (mirrors protocol v1 invariant).
        """
        # Invariant: high-risk requires approval resolution (break_glass exempt).
        if risk_level in ("high", "critical"):
            if approval_resolution_id is None and key_id != "break_glass":
                raise ValueError(
                    f"high-risk grant for '{tool_name}' requires "
                    f"approval_resolution_id (break_glass key_id is the only exemption)"
                )
            if key_id == "break_glass":
                logger.warning(
                    "break_glass grant issued for step %s tool %s — "
                    "requires post-hoc review",
                    step_run_id, tool_name,
                )

        # Generate 256-bit opaque handle.
        handle = secrets.token_urlsafe(32)  # ~43 chars, 256 bits entropy
        handle_digest = self._digest(handle)
        nonce = secrets.token_hex(16)  # 32 chars
        expires_at = datetime.now(UTC) + (ttl or _DEFAULT_TTL)

        grant = GrantRepository.create(
            self.db,
            tenant_id=tenant_id,
            step_run_id=step_run_id,
            handle_digest=handle_digest,
            nonce=nonce,
            bound_args_hash=bound_args_hash,
            risk_level=risk_level,
            resource_scope=resource_scope,
            security_context_digest=security_context_digest,
            approval_resolution_id=approval_resolution_id,
            key_id=key_id,
            status=GrantStatusDB.ISSUED,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
            max_uses=1,
            audience=audience,
        )

        logger.info(
            "Grant issued: grant_id=%s step=%s tool=%s risk=%s ttl=%ss",
            grant.id, step_run_id, tool_name, risk_level,
            int((ttl or _DEFAULT_TTL).total_seconds()),
        )

        return IssuedGrant(
            handle=handle,
            grant_id=grant.id,
            handle_digest=handle_digest,
            expires_at=expires_at,
        )

    def verify(self, handle: str) -> VerifiedGrant:
        """Verify a plaintext handle against the DB.

        Recomputes digest(handle), looks up the row, then checks:
        status=ISSUED, not expired, not consumed, not revoked.
        Does NOT consume — call consume() for that.
        """
        handle_digest = self._digest(handle)
        grant = GrantRepository.get_by_handle_digest(self.db, handle_digest)

        if grant is None:
            return VerifiedGrant(
                grant_id="", step_run_id="", tenant_id="",
                bound_args_hash="", resource_scope={}, risk_level="",
                expires_at=datetime.now(UTC),
                valid=False, reason="grant not found (unknown handle)",
            )

        if grant.status == GrantStatusDB.CONSUMED:
            return self._mk_invalid(grant, "grant already consumed (nonce replay)")
        if grant.status == GrantStatusDB.REVOKED:
            return self._mk_invalid(grant, "grant revoked")
        if grant.status == GrantStatusDB.EXPIRED:
            return self._mk_invalid(grant, "grant expired")
        # Check raw expiry (normalize for SQLite naive datetimes).
        now = datetime.now(UTC)
        expires = grant.expires_at
        if expires.tzinfo is None:
            now = now.replace(tzinfo=None)
        if expires <= now:
            return self._mk_invalid(grant, "grant expired")

        return VerifiedGrant(
            grant_id=grant.id,
            step_run_id=grant.step_run_id,
            tenant_id=grant.tenant_id,
            bound_args_hash=grant.bound_args_hash,
            resource_scope=grant.resource_scope,
            risk_level=grant.risk_level,
            expires_at=grant.expires_at,
            valid=True,
        )

    def consume(self, handle: str) -> bool:
        """Atomically mark a grant CONSUMED. Returns True if this call won.

        Uses GrantRepository.consume() which does a conditional UPDATE
        (WHERE status='issued'), so concurrent consumers cannot both
        succeed — exactly one gets True.
        """
        handle_digest = self._digest(handle)
        grant = GrantRepository.get_by_handle_digest(self.db, handle_digest)
        if grant is None:
            return False
        return GrantRepository.consume(self.db, grant.id)

    def revoke(self, grant_id: str) -> bool:
        """Revoke a grant (only works if not yet consumed)."""
        grant = GrantRepository.revoke(self.db, grant_id)
        if grant is not None and grant.status == GrantStatusDB.REVOKED:
            logger.warning("Grant revoked: grant_id=%s", grant_id)
            return True
        return False

    def expire_stale(self) -> int:
        """Mark all expired-but-ISSUED grants as EXPIRED. Returns count."""
        return GrantRepository.expire_stale(self.db)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mk_invalid(grant: Any, reason: str) -> VerifiedGrant:
        """Build a VerifiedGrant with valid=False for a known-invalid grant."""
        return VerifiedGrant(
            grant_id=grant.id,
            step_run_id=grant.step_run_id,
            tenant_id=grant.tenant_id,
            bound_args_hash=grant.bound_args_hash,
            resource_scope=grant.resource_scope,
            risk_level=grant.risk_level,
            expires_at=grant.expires_at,
            valid=False,
            reason=reason,
        )
