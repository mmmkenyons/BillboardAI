"""Sprint 5B research queue service (Qt-free).

Owns the durable batch-research workflow, coordinating:

- ``ProspectStore`` / ``ProspectWorkspaceService`` (prospect records)
- a :class:`~gui.models.research_job_store.ResearchQueueStore` (durable jobs)
- a :class:`~gui.services.research_pipeline.ResearchPipelineService` (research)

Responsibilities:
- enqueue (with duplicate / readiness / already-succeeded guards)
- inspect the queue (list / counts / filters)
- claim + run jobs (bounded concurrency, cooperative stop-after-current)
- persist status transitions and the prospect's high-level ``research_status``
- recover stale RUNNING jobs after a restart
- schedule conservative deterministic retries
- cancel queued / retry-pending jobs

This module never imports Qt and never launches a browser itself — it calls the
injected pipeline, so tests can substitute fake scrapers/engines.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from gui.models.prospect import Prospect
from gui.models.research_job import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAYS,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    ResearchJob,
    retry_delay_for_attempt,
    utc_now_iso,
)
from gui.models.research_job_store import ResearchQueueStore
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.services.research_pipeline import ResearchPipelineService, ResearchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prospect research_status (high-level reflection of queue state)
# These are distinct from Prospect.status (lifecycle).
# ---------------------------------------------------------------------------
PROSPECT_NOT_READY = "NOT_READY"
PROSPECT_READY = "READY"
PROSPECT_QUEUED = "QUEUED"
PROSPECT_RUNNING = "RUNNING"
PROSPECT_SUCCEEDED = "SUCCEEDED"
PROSPECT_FAILED = "FAILED"

PROSPECT_RESEARCH_STATUSES: tuple = (
    PROSPECT_NOT_READY,
    PROSPECT_READY,
    PROSPECT_QUEUED,
    PROSPECT_RUNNING,
    PROSPECT_SUCCEEDED,
    PROSPECT_FAILED,
)

# Recovered-after-interrupt note recorded in job metadata / error fields.
_RECOVERED_NOTE = "Recovered after interrupted session"


@dataclass
class ResearchBatchResult:
    """Summary of one queue execution pass."""

    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    cancelled: int = 0
    skipped: int = 0


class ResearchQueueService:
    """Qt-free coordinator for the durable batch research queue."""

    def __init__(
        self,
        prospect_service: Optional[ProspectWorkspaceService] = None,
        job_store: Optional[ResearchQueueStore] = None,
        pipeline: Optional[ResearchPipelineService] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delays: tuple = DEFAULT_RETRY_DELAYS,
        now_fn: Optional[Callable[[], str]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._prospect_service = prospect_service or ProspectWorkspaceService()
        self._job_store = job_store or ResearchQueueStore()
        self._pipeline = pipeline or ResearchPipelineService()
        self._max_attempts = max_attempts
        self._retry_delays = retry_delays
        self._now_fn = now_fn or utc_now_iso
        self._sleep_fn = sleep_fn or threading.Event().wait
        self._loaded = False
        self._io_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def job_store(self) -> ResearchQueueStore:
        return self._job_store

    @property
    def prospect_service(self) -> ProspectWorkspaceService:
        return self._prospect_service

    @property
    def pipeline(self) -> ResearchPipelineService:
        return self._pipeline

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Load both stores safely (empty when missing, no crash on corrupt)."""
        if self._loaded:
            return
        try:
            self._prospect_service.load()
        except FileNotFoundError:
            self._prospect_service.load_or_empty()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Prospect load failed during queue init: %s", exc)
        try:
            self._job_store.load_or_empty()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Queue load failed during init: %s", exc)
        self._loaded = True

    def _prospect(self, prospect_id: str) -> Optional[Prospect]:
        return self._prospect_service.get_prospect(prospect_id)
    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def list_jobs(self) -> List[ResearchJob]:
        """Return all jobs, deterministically ordered by (created_at, job_id)."""
        self.ensure_loaded()
        return self._job_store.list()

    def get_job(self, job_id: str) -> Optional[ResearchJob]:
        self.ensure_loaded()
        return self._job_store.get(job_id)

    def counts(self) -> Dict[str, int]:
        """Return summary queue counts keyed by human-friendly label."""
        self.ensure_loaded()
        jobs = self._job_store.list()
        by_status: Dict[str, int] = {}
        for job in jobs:
            by_status[job.status] = by_status.get(job.status, 0) + 1
        running = by_status.get(STATUS_RUNNING, 0)
        retry = by_status.get(STATUS_RETRY_PENDING, 0)
        pending = by_status.get(STATUS_PENDING, 0)
        return {
            "queued": pending + retry,
            "running": running,
            "succeeded": by_status.get(STATUS_SUCCEEDED, 0),
            "failed": by_status.get(STATUS_FAILED, 0),
            "retry_pending": retry,
            "cancelled": by_status.get(STATUS_CANCELLED, 0),
            "total": len(jobs),
        }

    def active_for_prospect(self, prospect_id: str) -> Optional[ResearchJob]:
        self.ensure_loaded()
        return self._job_store.collection.active_for_prospect(prospect_id)

    def succeeded_for_prospect(self, prospect_id: str) -> Optional[ResearchJob]:
        self.ensure_loaded()
        return self._job_store.collection.succeeded_for_prospect(prospect_id)

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------
    def enqueue_prospect(
        self,
        prospect_id: str,
        force: bool = False,
        reason: Optional[List[str]] = None,
    ) -> bool:
        """Enqueue a prospect for research if it is eligible.

        Eligibility (unless ``force``):
        - the prospect exists and is_ready_for_research()
        - not already SUCCEEDED (ready prospects)
        - no active (pending/running/retry) job already exists

        Returns True when a new PENDING job was created.
        """
        self.ensure_loaded()
        reason = reason if reason is not None else []
        prospect = self._prospect(prospect_id)
        if prospect is None:
            reason.append("prospect not found")
            return False
        if not force and not prospect.is_ready_for_research():
            reason.append("not ready for research")
            return False
        active = self.active_for_prospect(prospect_id)
        if active is not None:
            reason.append(f"already {active.status}")
            return False
        if not force and self.succeeded_for_prospect(prospect_id) is not None:
            reason.append("already succeeded")
            return False

        job = ResearchJob(
            prospect_id=prospect_id,
            website=prospect.website or prospect.domain or "",
            status=STATUS_PENDING,
            max_attempts=self._max_attempts,
        )
        job.created_at = self._now_fn()
        self._job_store.put(job)
        self._set_prospect_research_status(prospect_id, PROSPECT_QUEUED)
        logger.info(
            "Enqueued prospect_id=%s job_id=%s company=%s",
            prospect_id,
            job.job_id,
            prospect.company_name,
        )
        return True

    def enqueue_ready_prospects(self, limit: Optional[int] = None) -> int:
        """Enqueue all eligible ready prospects (up to ``limit``). Returns count."""
        self.ensure_loaded()
        count = 0
        for prospect in self._prospect_service.list_prospects():
            if limit is not None and limit > 0 and count >= limit:
                break
            reason: List[str] = []
            if self.enqueue_prospect(prospect.prospect_id, reason=reason):
                count += 1
        return count

    def _set_prospect_research_status(
        self, prospect_id: str, status: str
    ) -> None:
        """Update a prospect's high-level research_status and persist."""
        prospect = self._prospect(prospect_id)
        if prospect is None:
            return
        if prospect.research_status != status:
            prospect.research_status = status
            prospect.touch()
            try:
                self._prospect_service.save()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist prospect research_status: %s", exc)
# ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------
    def claim_next_job(self) -> Optional[ResearchJob]:
        """Claim the next due job (PENDING or due RETRY_PENDING) as RUNNING.

        Returns the claimed job, or None when nothing is due. Deterministic:
        the earliest-created due job wins.
        """
        self.ensure_loaded()
        now = self._now_fn()
        with self._io_lock:
            due: List[ResearchJob] = []
            for job in self._job_store.list():
                if job.is_due(now):
                    due.append(job)
            if not due:
                return None
            due.sort()
            job = due[0]
            job.status = STATUS_RUNNING
            job.run_id = str(uuid.uuid4())
            job.started_at = now
            job.last_error = ""
            job.last_error_type = ""
            job.attempt_count += 1
            self._job_store.put(job)
            self._set_prospect_research_status(job.prospect_id, PROSPECT_RUNNING)
            return job

    def complete_job(self, job: ResearchJob, result: ResearchResult) -> None:
        """Apply a pipeline result to a job and persist status + prospect state."""
        with self._io_lock:
            if result.success:
                job.status = STATUS_SUCCEEDED
                job.completed_at = self._now_fn()
                job.next_retry_at = ""
                if result.project_id:
                    job.project_id = result.project_id
                self._job_store.put(job)
                self._set_prospect_research_status(
                    job.prospect_id, PROSPECT_SUCCEEDED
                )
                return
            # Failure path.
            job.last_error = result.error
            job.last_error_type = result.error_type or "unknown"
            if result.retryable and job.retry_attempts_remaining() > 0:
                self._schedule_retry(job)
            else:
                job.status = STATUS_FAILED
                job.completed_at = self._now_fn()
                job.next_retry_at = ""
                self._job_store.put(job)
                self._set_prospect_research_status(
                    job.prospect_id, PROSPECT_FAILED
                )

    def _schedule_retry(self, job: ResearchJob) -> None:
        """Move a job to RETRY_PENDING with a deterministic delay."""
        delay = retry_delay_for_attempt(job.attempt_count - 1, self._retry_delays)
        now = self._now_fn()
        job.status = STATUS_RETRY_PENDING
        job.completed_at = ""
        job.next_retry_at = _add_seconds(now, delay)
        self._job_store.put(job)
        # Research is still outstanding -> prospect stays QUEUED (awaiting run).
        self._set_prospect_research_status(job.prospect_id, PROSPECT_QUEUED)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a non-running, non-terminal job. Returns True if cancelled."""
        job = self.get_job(job_id)
        if job is None:
            return False
        if job.status in (STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED):
            return False
        job.status = STATUS_CANCELLED
        job.completed_at = self._now_fn()
        self._job_store.put(job)
        self._set_prospect_research_status(job.prospect_id, PROSPECT_READY)
        return True

    def cancel_pending(self) -> int:
        """Cancel all queued (PENDING / RETRY_PENDING) jobs. Returns count."""
        self.ensure_loaded()
        count = 0
        for job in self._job_store.list():
            if job.status in (STATUS_PENDING, STATUS_RETRY_PENDING):
                if self.cancel_job(job.job_id):
                    count += 1
        return count

    def retry_failed_jobs(self, limit: Optional[int] = None) -> int:
        """Re-enqueue FAILED jobs as fresh PENDING jobs. Returns count."""
        self.ensure_loaded()
        count = 0
        for job in self._job_store.list():
            if limit is not None and limit > 0 and count >= limit:
                break
            if job.status != STATUS_FAILED:
                continue
            # Reuse the same job but reset to a fresh pending attempt.
            job.status = STATUS_PENDING
            job.completed_at = ""
            job.next_retry_at = ""
            job.last_error = ""
            job.last_error_type = ""
            self._job_store.put(job)
            self._set_prospect_research_status(job.prospect_id, PROSPECT_QUEUED)
            count += 1
        return count

    def recover_stale(self) -> int:
        """Recover RUNNING jobs from an interrupted session -> RETRY_PENDING.

        Returns the number of jobs recovered. A recovered job will be picked up
        on the next run (after its retry delay) and will not duplicate Projects
        because idempotency is enforced at project creation time.
        """
        self.ensure_loaded()
        count = 0
        for job in self._job_store.list():
            if job.status != STATUS_RUNNING:
                continue
            job.status = STATUS_RETRY_PENDING
            job.completed_at = ""
            job.next_retry_at = self._now_fn()
            note = f"{_RECOVERED_NOTE} (attempt {job.attempt_count})"
            job.metadata["recovery_note"] = note
            if not job.last_error:
                job.last_error = _RECOVERED_NOTE
            if not job.last_error_type:
                job.last_error_type = "interrupted"
            self._job_store.put(job)
            self._set_prospect_research_status(job.prospect_id, PROSPECT_QUEUED)
            count += 1
        return count

# ------------------------------------------------------------------
    # Execution (coordinator)
    # ------------------------------------------------------------------
    def run_batch(
        self,
        limit: int,
        concurrency: int = 1,
        stop_event: Optional[threading.Event] = None,
        progress: Optional[Callable[[str, str, str], None]] = None,
    ) -> ResearchBatchResult:
        """Execute up to ``limit`` due jobs with bounded concurrency.

        Signature of ``progress``: ``(stage, company, job_id)``.

        Cooperative cancel: the ``stop_event`` (a ``threading.Event``) is checked
        before each new job is claimed. Jobs already claimed/started complete
        normally; unclaimed queued jobs are left in the queue.
        """
        summary = ResearchBatchResult()
        limit = max(1, int(limit or 1))
        concurrency = max(1, int(concurrency or 1))
        self.ensure_loaded()
        self.recover_stale()

        claimed: List[ResearchJob] = []
        # 1. Reserve due jobs (respecting the stop signal between claims).
        for _ in range(limit):
            if stop_event is not None and stop_event.is_set():
                break
            with self._io_lock:
                claim = self.claim_next_job()
            if claim is None:
                break
            claimed.append(claim)

        if not claimed:
            return summary

        summary.claimed = len(claimed)

        def _run(claim: ResearchJob) -> str:
            prospect = self._prospect(claim.prospect_id)
            if prospect is None:  # prospect vanished -> cancel the orphan job
                with self._io_lock:
                    claim.status = STATUS_CANCELLED
                    claim.completed_at = self._now_fn()
                    self._job_store.put(claim)
                return "cancelled"

            def _cb(stage: str) -> None:
                if callable(progress):
                    progress(str(stage), prospect.company_name, claim.job_id)

            result = self._pipeline.run(prospect, progress_callback=_cb)
            with self._io_lock:
                self.complete_job(claim, result)
            if result.success:
                return "succeeded"
            if result.retryable:
                return "retried"
            return "failed"

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(_run, claim) for claim in claimed]
            for future in futures:
                outcome = future.result()
                if outcome == "succeeded":
                    summary.succeeded += 1
                elif outcome == "retried":
                    summary.retried += 1
                elif outcome == "cancelled":
                    summary.cancelled += 1
                else:
                    summary.failed += 1

        logger.info(
            "Batch run complete claimed=%d succeeded=%d failed=%d retried=%d",
            summary.claimed,
            summary.succeeded,
            summary.failed,
            summary.retried,
        )
        return summary


def _add_seconds(iso: str, seconds: int) -> str:
    """Add ``seconds`` to an ISO-8601 UTC timestamp (string, second precision)."""
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        dt = datetime.fromisoformat(utc_now_iso())
    result = dt + timedelta(seconds=int(seconds))
    return result.replace(microsecond=0).isoformat()