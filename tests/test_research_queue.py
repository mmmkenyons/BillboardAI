"""Sprint 5B research queue test suite (Qt-free, no network).

Covers: the ResearchJob model, the ResearchQueueStore, enqueue rules, status
transitions, retry policy, restart recovery, cancel, and bounded queue
execution. A fake pipeline is injected so no browser / live website is used.
"""

from __future__ import annotations

import os
import threading

import pytest

from engine.ad_concept import AdConcept
from engine.brand_profile import BrandProfile
from engine.message_strategy import MessageStrategy
from gui.models.prospect_store import ProspectStore
from gui.models.research_job import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    ResearchJob,
)
from gui.models.research_job_store import (
    ResearchQueueCorruptionError,
    ResearchQueueStore,
)
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.services.research_pipeline import ResearchResult
from gui.services.research_queue import (
    PROSPECT_FAILED,
    PROSPECT_QUEUED,
    PROSPECT_READY,
    PROSPECT_RUNNING,
    PROSPECT_SUCCEEDED,
    ResearchQueueService,
)


class FakePipeline:
    """Deterministic success/failure pipeline for queue tests."""

    def __init__(
        self,
        success: bool = True,
        retryable: bool = False,
        project_id: str = "proj-X",
        error: str = "boom",
        retry_after: int = 0,
    ) -> None:
        self.success = success
        self.retryable = retryable
        self.project_id = project_id
        self.error = error
        self.retry_after = retry_after  # succeed after this many failures
        self.calls: list = []

    def run(self, prospect, progress_callback=None):
        self.calls.append(prospect.prospect_id)
        if callable(progress_callback):
            progress_callback("Scraping")
        if self.success and len(self.calls) > self.retry_after:
            return ResearchResult(
                success=True,
                prospect_id=prospect.prospect_id,
                project_id=self.project_id,
                brand_profile=BrandProfile(company_name=prospect.company_name),
                strategies=[MessageStrategy()],
                concepts=[AdConcept()],
            )
        return ResearchResult(
            success=False,
            prospect_id=prospect.prospect_id,
            error=self.error,
            error_type="scrape_transient" if self.retryable else "invalid_url",
            retryable=self.retryable,
        )


def build(tmp_path, pipeline=None, max_attempts=3, retry_delays=(0, 0, 0), now_fn=None):
    """Build a research queue service with temp stores + a fake pipeline."""
    pstore = ProspectStore(path=str(tmp_path / "prospects.json"))
    psvc = ProspectWorkspaceService(store=pstore)
    jstore = ResearchQueueStore(path=str(tmp_path / "queue.json"))
    pipe = pipeline if pipeline is not None else FakePipeline()
    svc = ResearchQueueService(
        prospect_service=psvc,
        job_store=jstore,
        pipeline=pipe,
        max_attempts=max_attempts,
        retry_delays=retry_delays,
        now_fn=now_fn,
    )
    svc.ensure_loaded()
    return svc, psvc, jstore


def seed_prospects(psvc, pairs):
    psvc.load()
    ids = []
    for name, site in pairs:
        p = psvc.create_prospect(company_name=name, website=site)
        ids.append(p.prospect_id)
    return ids
# ---------------------------------------------------------------------------
# RESEARCH JOB MODEL
# ---------------------------------------------------------------------------


class TestResearchJobModel:
    def test_minimal_construction(self) -> None:
        job = ResearchJob()
        assert job.job_id
        assert job.status == "PENDING"
        assert job.attempt_count == 0

    def test_unique_ids(self) -> None:
        assert ResearchJob().job_id != ResearchJob().job_id

    def test_serialization_round_trip(self) -> None:
        job = ResearchJob(
            prospect_id="p1",
            website="https://x.com",
            attempt_count=2,
            project_id="proj-1",
            status=STATUS_SUCCEEDED,
        )
        restored = ResearchJob.from_dict(job.to_dict())
        assert restored.prospect_id == "p1"
        assert restored.website == "https://x.com"
        assert restored.attempt_count == 2
        assert restored.project_id == "proj-1"
        assert restored.status == STATUS_SUCCEEDED

    def test_unknown_fields_safe(self) -> None:
        job = ResearchJob.from_dict({"job_id": "j1", "future_field": "x"})
        assert job.job_id == "j1"
        assert hasattr(job, "prospect_id")

    def test_missing_fields_safe(self) -> None:
        job = ResearchJob.from_dict({"job_id": "j2"})
        assert job.status == "PENDING"
        assert job.prospect_id == ""
        assert job.metadata == {}

    def test_status_validation(self) -> None:
        assert ResearchJob.from_dict({"status": "BOGUS"}).status == "PENDING"
        assert ResearchJob.from_dict({"status": STATUS_CANCELLED}).status == STATUS_CANCELLED

    def test_attempts_persist(self) -> None:
        assert ResearchJob.from_dict({"attempt_count": "3"}).attempt_count == 3

    def test_error_fields_persist(self) -> None:
        job = ResearchJob.from_dict(
            {"job_id": "j", "last_error": "x", "last_error_type": "scrape_transient"}
        )
        assert job.last_error == "x"
        assert job.last_error_type == "scrape_transient"

    def test_project_id_persists(self) -> None:
        assert ResearchJob.from_dict({"project_id": "proj-9"}).project_id == "proj-9"

    def test_active_and_terminal(self) -> None:
        assert ResearchJob(status=STATUS_PENDING).is_active()
        assert ResearchJob(status=STATUS_SUCCEEDED).is_terminal()
        assert not ResearchJob(status=STATUS_SUCCEEDED).is_active()


# ---------------------------------------------------------------------------
# QUEUE STORE
# ---------------------------------------------------------------------------


class TestResearchQueueStore:
    def test_enqueue(self, tmp_path) -> None:
        store = ResearchQueueStore(path=str(tmp_path / "q.json"))
        store.put(ResearchJob(prospect_id="p"))
        assert store.exists()
        assert len(store.list()) == 1

    def test_save_load(self, tmp_path) -> None:
        store = ResearchQueueStore(path=str(tmp_path / "q.json"))
        store.put(ResearchJob(prospect_id="p1"))
        store.put(ResearchJob(prospect_id="p2"))
        store2 = ResearchQueueStore(path=str(tmp_path / "q.json"))
        store2.load()
        assert len(store2.list()) == 2

    def test_atomic_save(self, tmp_path) -> None:
        path = str(tmp_path / "q.json")
        store = ResearchQueueStore(path=path)
        store.put(ResearchJob(prospect_id="p"))
        assert not os.path.exists(path + ".tmp")

    def test_corruption_handled(self, tmp_path) -> None:
        path = str(tmp_path / "q.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        store = ResearchQueueStore(path=path)
        with pytest.raises(ResearchQueueCorruptionError):
            store.load()

    def test_deterministic_ordering(self, tmp_path) -> None:
        store = ResearchQueueStore(path=str(tmp_path / "q.json"))
        a = ResearchJob(prospect_id="a", created_at="2026-01-01T00:00:00")
        b = ResearchJob(prospect_id="b", created_at="2026-01-02T00:00:00")
        store.put(b)
        store.put(a)
        assert [j.prospect_id for j in store.list()] == ["a", "b"]

    def test_filter_by_status(self, tmp_path) -> None:
        store = ResearchQueueStore(path=str(tmp_path / "q.json"))
        store.put(ResearchJob(prospect_id="a", status=STATUS_PENDING))
        store.put(ResearchJob(prospect_id="b", status=STATUS_SUCCEEDED))
        got = store.collection.by_status(STATUS_SUCCEEDED)
        assert [j.prospect_id for j in got] == ["b"]

    def test_filter_by_prospect(self, tmp_path) -> None:
        store = ResearchQueueStore(path=str(tmp_path / "q.json"))
        store.put(ResearchJob(prospect_id="p", job_id="j1"))
        store.put(ResearchJob(prospect_id="q", job_id="j2"))
        assert [j.job_id for j in store.collection.by_prospect("p")] == ["j1"]

    def test_no_duplicate_active_jobs_detection(self, tmp_path) -> None:
        store = ResearchQueueStore(path=str(tmp_path / "q.json"))
        store.put(ResearchJob(prospect_id="p", status=STATUS_PENDING))
        assert store.collection.active_for_prospect("p") is not None
        assert store.collection.active_for_prospect("other") is None


def _ready_prospect(psvc, name="Acme", site="acme.com"):
    """Create a single website-bearing prospect and return its id."""
    return psvc.create_prospect(company_name=name, website=site).prospect_id


# ---------------------------------------------------------------------------
# QUEUE SERVICE: ENQUEUE
# ---------------------------------------------------------------------------


class TestQueueEnqueue:
    def test_enqueue_creates_pending_job(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        assert svc.enqueue_prospect(pid) is True
        jobs = svc.list_jobs()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.prospect_id == pid
        assert job.status == STATUS_PENDING
        assert job.website == "https://acme.com"
        assert psvc.get_prospect(pid).research_status == PROSPECT_QUEUED

    def test_enqueue_missing_prospect(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        reasons: list = []
        assert svc.enqueue_prospect("nope", reason=reasons) is False
        assert reasons == ["prospect not found"]

    def test_enqueue_not_ready(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = psvc.create_prospect(company_name="NoSite").prospect_id
        reasons: list = []
        assert svc.enqueue_prospect(pid, reason=reasons) is False
        assert reasons == ["not ready for research"]

    def test_enqueue_rejects_duplicate_active(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        assert svc.enqueue_prospect(pid) is True
        reasons: list = []
        assert svc.enqueue_prospect(pid, reason=reasons) is False
        assert reasons and reasons[0].startswith("already")

    def test_enqueue_rejects_already_succeeded(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        svc.complete_job(
            job, ResearchResult(success=True, prospect_id=pid, project_id="proj-1")
        )
        reasons: list = []
        assert svc.enqueue_prospect(pid, reason=reasons) is False
        assert reasons == ["already succeeded"]
        # force bypasses the succeeded guard and re-queues.
        assert svc.enqueue_prospect(pid, force=True) is True


# ---------------------------------------------------------------------------
# QUEUE SERVICE: STATUS TRANSITIONS
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    def test_claim_next_job_marks_running(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        assert job is not None
        assert job.status == STATUS_RUNNING
        assert job.attempt_count == 1
        assert job.run_id
        assert psvc.get_prospect(pid).research_status == PROSPECT_RUNNING

    def test_claim_none_when_empty(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        assert svc.claim_next_job() is None

    def test_complete_success_serializes_project(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        svc.complete_job(
            job, ResearchResult(success=True, prospect_id=pid, project_id="proj-9")
        )
        assert job.status == STATUS_SUCCEEDED
        assert job.project_id == "proj-9"
        assert job.completed_at
        assert psvc.get_prospect(pid).research_status == PROSPECT_SUCCEEDED

    def test_complete_permanent_failure(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        svc.complete_job(
            job,
            ResearchResult(
                success=False,
                prospect_id=pid,
                error="bad",
                error_type="invalid_url",
                retryable=False,
            ),
        )
        assert job.status == STATUS_FAILED
        assert job.last_error == "bad"
        assert psvc.get_prospect(pid).research_status == PROSPECT_FAILED


# ---------------------------------------------------------------------------
# QUEUE SERVICE: RETRY
# ---------------------------------------------------------------------------


class TestRetry:
    def test_retryable_failure_schedules_retry(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path, retry_delays=(60, 300, 900))
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        svc.complete_job(
            job,
            ResearchResult(
                success=False,
                prospect_id=pid,
                error="boom",
                error_type="scrape_transient",
                retryable=True,
            ),
        )
        assert job.status == STATUS_RETRY_PENDING
        assert job.next_retry_at
        assert job.next_retry_at >= job.started_at
        # Research is still outstanding -> prospect remains QUEUED.
        assert psvc.get_prospect(pid).research_status == PROSPECT_QUEUED

    def test_retry_exhausted_fails(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path, max_attempts=1)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        assert job.retry_attempts_remaining() == 0
        svc.complete_job(
            job,
            ResearchResult(
                success=False,
                prospect_id=pid,
                error="boom",
                error_type="scrape_transient",
                retryable=True,
            ),
        )
        assert job.status == STATUS_FAILED

    def test_retry_delay_uses_ladder(self, tmp_path) -> None:
        now = ["2026-01-01T00:00:00"]
        svc, psvc, _ = build(
            tmp_path, retry_delays=(60, 300, 900), now_fn=lambda: now[0]
        )
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()
        svc.complete_job(
            job,
            ResearchResult(
                success=False,
                prospect_id=pid,
                error="boom",
                error_type="scrape_transient",
                retryable=True,
            ),
        )
        assert job.next_retry_at == "2026-01-01T00:01:00"


# ---------------------------------------------------------------------------
# QUEUE SERVICE: RECOVERY
# ---------------------------------------------------------------------------


class TestRecovery:
    def test_recover_stale_running_job(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        job = svc.claim_next_job()  # simulate crash while RUNNING
        assert job.status == STATUS_RUNNING
        assert svc.recover_stale() == 1
        recovered = svc.get_job(job.job_id)
        assert recovered.status == STATUS_RETRY_PENDING
        assert recovered.metadata.get("recovery_note")
        assert recovered.last_error_type == "interrupted"
        assert psvc.get_prospect(pid).research_status == PROSPECT_QUEUED

    def test_recover_skips_non_running_jobs(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        assert svc.recover_stale() == 0
        assert svc.list_jobs()[0].status == STATUS_PENDING


# ---------------------------------------------------------------------------
# QUEUE SERVICE: EXECUTION (bounded batch runs)
# ---------------------------------------------------------------------------


class TestExecution:
    def test_run_batch_success(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pids = seed_prospects(psvc, [("Acme", "acme.com"), ("Beta", "beta.com")])
        for pid in pids:
            svc.enqueue_prospect(pid)
        result = svc.run_batch(limit=2)
        assert result.claimed == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert {j.status for j in svc.list_jobs()} == {STATUS_SUCCEEDED}

    def test_run_batch_honors_limit(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pids = seed_prospects(psvc, [("A", "a.com"), ("B", "b.com"), ("C", "c.com")])
        for pid in pids:
            svc.enqueue_prospect(pid)
        result = svc.run_batch(limit=2)
        assert result.claimed == 2
        assert result.succeeded == 2
        statuses = [j.status for j in svc.list_jobs()]
        assert statuses.count(STATUS_SUCCEEDED) == 2
        assert statuses.count(STATUS_PENDING) == 1

    def test_run_batch_retryable(self, tmp_path) -> None:
        svc, psvc, _ = build(
            tmp_path,
            pipeline=FakePipeline(success=False, retryable=True),
            retry_delays=(0, 0, 0),
        )
        pid = _ready_prospect(psvc)
        svc.enqueue_prospect(pid)
        result = svc.run_batch(limit=1)
        assert result.claimed == 1
        assert result.retried == 1
        assert svc.list_jobs()[0].status == STATUS_RETRY_PENDING

    def test_run_batch_stop_event_prevents_claims(self, tmp_path) -> None:
        svc, psvc, _ = build(tmp_path)
        pids = seed_prospects(psvc, [("A", "a.com"), ("B", "b.com")])
        for pid in pids:
            svc.enqueue_prospect(pid)
        stop = threading.Event()
        stop.set()
        result = svc.run_batch(limit=2, stop_event=stop)
        assert result.claimed == 0
        assert all(j.status == STATUS_PENDING for j in svc.list_jobs())

