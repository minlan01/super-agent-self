"""LeaseManager — WorkerBroker's Lease ownership with fencing tokens.

Spec §4.3 + PROJECT-CONTEXT §状态与所有权不变量:
  - WorkerBroker owns Lease creation, renewal, release, fencing monotonicity.
  - fencing_token is monotonic per (worker_id, step_run_id).
  - Stale workers with old fencing tokens cannot commit results.
  - Expired/released leases cannot be used for new dispatch.

This is the sole write-owner of the leases table.  Other modules (EffectJournal,
ToolGateway) only READ lease state or call is_valid().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from packages.db.models import LeaseStatus
from packages.db.repositories.lease_repo import LeaseRepository

logger = structlog.get_logger()

# Default lease duration (10 minutes — longer than a typical step timeout
# but short enough to expire if a worker crashes without heartbeat).
_DEFAULT_LEASE_TTL = timedelta(minutes=10)
_HEARTBEAT_EXTEND = timedelta(minutes=5)


@dataclass(frozen=True)
class AcquiredLease:
    """Result of acquire(): the lease metadata for the caller."""
    lease_id: str
    worker_id: str
    step_run_id: str
    fencing_token: int
    expires_at: datetime


class LeaseManager:
    """Sole owner of the leases table.

    fencing_token assignment (PROJECT-CONTEXT invariant: monotonic per worker+step):
      next_token = max(existing fencing_token for this worker+step) + 1
      This ensures that even if a worker's old lease expires and it re-acquires,
      the new token is strictly greater than the old one.
    """

    def __init__(self, db: Session):
        self.db = db

    def acquire(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        step_run_id: str,
        ttl: timedelta | None = None,
    ) -> AcquiredLease:
        """Acquire (or re-acquire) a lease for a step.

        If an ACTIVE lease already exists for this step and is owned by the
        same worker, extends it.  If owned by a different worker, the old
        lease must be released/expired first — we do NOT steal leases.

        fencing_token is always max(existing_for_this_worker+step) + 1,
        ensuring monotonicity across re-acquisitions.
        """
        # Check for existing active lease.
        existing = LeaseRepository.get_active_by_step(
            self.db, tenant_id=tenant_id, step_run_id=step_run_id,
        )

        if existing is not None:
            if existing.worker_id == worker_id:
                # Same worker re-acquiring: extend the existing lease.
                new_expires = datetime.now(UTC) + (ttl or _DEFAULT_LEASE_TTL)
                LeaseRepository.renew(self.db, existing.id, new_expires)
                logger.info(
                    "Lease extended: lease=%s worker=%s step=%s expires=%s",
                    existing.id, worker_id, step_run_id, new_expires.isoformat(),
                )
                return AcquiredLease(
                    lease_id=existing.id,
                    worker_id=worker_id,
                    step_run_id=step_run_id,
                    fencing_token=existing.fencing_token,
                    expires_at=new_expires,
                )
            # Different worker owns the active lease — fail closed.
            raise LeaseConflictError(
                f"step {step_run_id} already has an active lease owned by "
                f"worker {existing.worker_id}"
            )

        # No active lease: assign next monotonic fencing_token for this worker+step.
        max_token = LeaseRepository.get_max_fencing_token(
            self.db, worker_id=worker_id, step_run_id=step_run_id,
        )
        fencing_token = max_token + 1
        expires_at = datetime.now(UTC) + (ttl or _DEFAULT_LEASE_TTL)

        lease = LeaseRepository.create(
            self.db,
            tenant_id=tenant_id,
            worker_id=worker_id,
            step_run_id=step_run_id,
            fencing_token=fencing_token,
            status=LeaseStatus.ACTIVE,
            expires_at=expires_at,
            last_heartbeat_at=datetime.now(UTC),
        )

        logger.info(
            "Lease acquired: lease=%s worker=%s step=%s token=%d expires=%s",
            lease.id, worker_id, step_run_id, fencing_token, expires_at.isoformat(),
        )

        return AcquiredLease(
            lease_id=lease.id,
            worker_id=worker_id,
            step_run_id=step_run_id,
            fencing_token=fencing_token,
            expires_at=expires_at,
        )

    def heartbeat(self, lease_id: str) -> bool:
        """Extend a lease's expiry by HEARTBEAT_EXTEND. Returns False if expired/released."""
        lease = LeaseRepository.get_by_id(self.db, lease_id)
        if lease is None or lease.status != LeaseStatus.ACTIVE:
            return False
        # Normalize for SQLite naive datetimes.
        now = datetime.now(UTC)
        expires = lease.expires_at
        if expires.tzinfo is None:
            now = now.replace(tzinfo=None)
        if expires <= now:
            # Already expired — mark and reject.
            LeaseRepository.update_status(self.db, lease_id, LeaseStatus.EXPIRED)
            return False
        new_expires = datetime.now(UTC) + _HEARTBEAT_EXTEND
        LeaseRepository.renew(self.db, lease_id, new_expires)
        return True

    def release(self, lease_id: str) -> bool:
        """Release a lease (worker done). Returns False if already inactive/expired."""
        lease = LeaseRepository.get_by_id(self.db, lease_id)
        if lease is None or lease.status != LeaseStatus.ACTIVE:
            return False
        LeaseRepository.release(self.db, lease_id)
        logger.info("Lease released: lease=%s", lease_id)
        return True

    def is_valid(self, lease_id: str, fencing_token: int) -> bool:
        """Check if a lease is active, not expired, and fencing_token matches.

        This is the stale-token guard: an old worker that somehow retains a
        reference to a released/expired/superseded lease will fail this check.
        """
        return LeaseRepository.is_valid(self.db, lease_id, fencing_token)

    def expire_stale(self) -> int:
        """Mark all active-but-expired leases as EXPIRED. Returns count."""
        return LeaseRepository.expire_stale(self.db)

    def get_lease(self, lease_id: str) -> Any:
        """Read-only access to a lease record (for EffectJournal/ToolGateway)."""
        return LeaseRepository.get_by_id(self.db, lease_id)


class LeaseConflictError(Exception):
    """Raised when a worker tries to acquire a lease owned by another worker."""
