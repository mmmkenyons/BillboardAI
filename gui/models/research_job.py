"""Sprint 5B durable research-job domain model (Qt-free).

A **ResearchJob** is one stateful unit of research work for a single prospect.
It is deliberately separate from:

- ``Prospect``  — the business lead record (held in ``gui/models/prospect.py``).
- ``Project``   — the durable workspace created after successful research.

The job tracks *attempt* / *queue* state (status, attempts, errors, retry
timing, run id, persisted project id) so the batch research pipeline is
resumable and idempotent across retries and app restarts.

Design rules (mirroring the prospect model):

- **No Qt / no widgets.** This module never imports Qt.
- **Forward-compatible serialization.** ``to_dict`` / ``from_dict`` ignore
  unknown persisted fields and supply safe defaults for missing optional fields.
- **Small, explicit status set.** See :data:`JOB_STATUSES`.
- **No network / no browser.** Pure deterministic model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Status model (small, explicit)
# ---------------------------------------------------------------------------
STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_SUCCEEDED = "SUCCEEDED"
STATUS_FAILED = "FAILED"
STATUS_RETRY_PENDING = "RETRY_PENDING"
STATUS_CANCELLED = "CANCELLED"

JOB_STATUSES: tuple = (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_RETRY_PENDING,
    STATUS_CANCELLED,
)

# Terminal states (no further automatic transitions).
_TERMINAL = {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED}

# Default maximum attempts for a single research job.
DEFAULT_MAX_ATTEMPTS = 3

# Default conservative retry delays (seconds) indexed by attempt round.
# A job on its 1st failed transient attempt waits 60s, 2nd -> 300s, 3rd -> 900s.
DEFAULT_RETRY_DELAYS = (60, 300, 900)


def new_job_id() -> str:
    """Return a fresh, filesystem-safe, JSON-safe job id."""
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """Return the current UTC time as ISO-8601 (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: Any) -> str:
    """Coerce a value to a trimmed string (None -> empty)."""
    if value is None:
        return ""
    return str(value).strip()
@dataclass
class ResearchJob:
    """One durable unit of research work for a prospect.

    Attributes:
        job_id: Stable unique id for this job.
        prospect_id: The prospect this job researches.
        website: The normalized website URL researched by this job.
        status: One of :data:`JOB_STATUSES`.
        attempt_count: Number of claimed (run) attempts so far.
        max_attempts: Hard cap on attempts before the job is failed.
        created_at / started_at / completed_at: ISO-8601 timestamps.
        next_retry_at: ISO timestamp before which a RETRY_PENDING job waits.
        last_error: Concise human-readable error from the last attempt.
        last_error_type: Machine-readable error classification.
        project_id: The durable Project created/associated after success.
        run_id: Unique id for the latest run attempt (worker/session token).
        metadata: Free-form additive metadata.
    """

    job_id: str = field(default_factory=new_job_id)
    prospect_id: str = ""
    website: str = ""
    status: str = STATUS_PENDING
    attempt_count: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str = ""
    completed_at: str = ""
    next_retry_at: str = ""
    last_error: str = ""
    last_error_type: str = ""
    project_id: str = ""
    run_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for JSON persistence."""
        return {
            "job_id": self.job_id,
            "prospect_id": self.prospect_id,
            "website": self.website,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "next_retry_at": self.next_retry_at,
            "last_error": self.last_error,
            "last_error_type": self.last_error_type,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ResearchJob":
        """Deserialize from a dict, ignoring unknown fields safely."""
        if not isinstance(data, dict):
            data = {}
        status = _clean(data.get("status")) or STATUS_PENDING
        if status not in JOB_STATUSES:
            status = STATUS_PENDING
        try:
            attempt_count = int(data.get("attempt_count") or 0)
        except (TypeError, ValueError):
            attempt_count = 0
        try:
            max_attempts = int(data.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)
        except (TypeError, ValueError):
            max_attempts = DEFAULT_MAX_ATTEMPTS
        return cls(
            job_id=_clean(data.get("job_id")) or new_job_id(),
            prospect_id=_clean(data.get("prospect_id")),
            website=_clean(data.get("website")),
            status=status,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            created_at=_clean(data.get("created_at")) or utc_now_iso(),
            started_at=_clean(data.get("started_at")),
            completed_at=_clean(data.get("completed_at")),
            next_retry_at=_clean(data.get("next_retry_at")),
            last_error=_clean(data.get("last_error")),
            last_error_type=_clean(data.get("last_error_type")),
            project_id=_clean(data.get("project_id")),
            run_id=_clean(data.get("run_id")),
            metadata=dict(data.get("metadata") or {}),
        )

    # ------------------------------------------------------------------
    # Behavior
    # ------------------------------------------------------------------
    def is_terminal(self) -> bool:
        """Return True when the job will not transition automatically."""
        return self.status in _TERMINAL

    def is_active(self) -> bool:
        """Return True when the job is queued or currently running.

        Used to prevent duplicate active jobs for the same prospect.
        """
        return self.status in (STATUS_PENDING, STATUS_RUNNING, STATUS_RETRY_PENDING)

    def is_due(self, now: Optional[str] = None) -> bool:
        """Return True when the job is eligible to run RIGHT NOW.

        PENDING jobs are always due. RETRY_PENDING jobs are due once their
        ``next_retry_at`` has passed (or is empty/malformed).
        """
        if self.status == STATUS_PENDING:
            return True
        if self.status != STATUS_RETRY_PENDING:
            return False
        if not self.next_retry_at:
            return True
        now = now or utc_now_iso()
        try:
            return str(self.next_retry_at) <= now
        except Exception:  # noqa: BLE001 - malformed timestamp -> treat as due
            return True

    def retry_attempts_remaining(self) -> int:
        """Return how many more attempts are allowed before failing."""
        return max(0, self.max_attempts - self.attempt_count)

    def __lt__(self, other: object) -> bool:
        """Deterministic ordering by (created_at, job_id)."""
        if not isinstance(other, ResearchJob):
            return NotImplemented
        return (self.created_at, self.job_id) < (other.created_at, other.job_id)


def retry_delay_for_attempt(
    attempt_index: int, delays: tuple = DEFAULT_RETRY_DELAYS
) -> int:
    """Return the retry delay (seconds) for the given 0-based attempt index.

    Uses the provided delay ladder; clamps to the last configured delay when the
    index exceeds the ladder length.
    """
    if not delays:
        return 0
    if attempt_index < 0:
        return delays[0]
    if attempt_index < len(delays):
        return int(delays[attempt_index])
    return int(delays[-1])
