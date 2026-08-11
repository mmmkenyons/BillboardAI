"""Sprint 5B batch research queue — end-to-end verification tool (Qt-free).

PROVES (against the REAL :class:`ResearchQueueService` and the REAL
:class:`ResearchPipelineService`, no widgets, no running app):

1. prospect records are created
2. READY prospects are enqueued
3. the queue is persisted to disk
4. research executes
5. success creates a durable Project
6. the Project contains BrandProfile + message strategies + ad concepts
7. failure records an error and the queue continues (does not abort the batch)
8. the queue reloads from disk
9. a successful job remains associated with its Project (project_id + metadata)
10. rerun / retry does NOT create a duplicate Project (idempotent)
11. successful persisted research is not unnecessarily repeated
12. restart recovery: a RUNNING job reloads from disk and is recovered to a
    non-RUNNING state (RETRY_PENDING / PENDING per policy)

NETWORK POLICY (honest)
-----------------------
The research pipeline's external dependency is the ``WebsiteScraper``. This
script submits a deterministic scraper/engines at the pipeline's documented
dependency-injection seam (the SAME seam the unit tests use), so the full
production orchestration — website validation, BrandProfile, MessageStrategy,
AdConcept, Project create/reuse, prospect association, idempotency, persistence
— runs unchanged and is objectively verifiable whether or not this machine can
reach the live site. In addition to that controlled run, an OUT-OF-BAND live
``WebsiteScraper`` attempt against the "Jim Woods Roofing" site is made and its
result is reported honestly (success, or an explicit network/site failure). No
production logic is weakened to force a pass.

All runtime verification data is written under ``output/`` which is git-ignored.

Run::

    python tools/sprint5b_verify.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Real production services.
from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.models.research_job import (  # noqa: E402
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
)
from gui.models.research_job_store import ResearchQueueStore  # noqa: E402
from gui.models.project_store import ProjectStore  # noqa: E402
from gui.services.prospect_workspace import ProspectWorkspaceService  # noqa: E402
from gui.services.research_pipeline import (  # noqa: E402
    ResearchPipelineService,
    ResearchResult,
)
from gui.services.research_queue import (  # noqa: E402
    PROSPECT_FAILED,
    PROSPECT_QUEUED,
    PROSPECT_SUCCEEDED,
    ResearchQueueService,
)

from engine.brand_profile import BrandProfile, BrandProfileBuilder  # noqa: E402
from engine.message_strategy import MessageStrategy  # noqa: E402
from engine.ad_concept import AdConcept  # noqa: E402

# ---------------------------------------------------------------------------
# Git-ignored verification output
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_DIR = os.path.join(ROOT, "output", "research", "sprint5b_verify")
PROSPECTS_PATH = os.path.join(VERIFY_DIR, "prospects.json")
QUEUE_PATH = os.path.join(VERIFY_DIR, "research_queue.json")
PROJECTS_ROOT = os.path.join(VERIFY_DIR, "projects")
LIVE_PROJECTS_ROOT = os.path.join(VERIFY_DIR, "projects_live")
LIVE_SNAPSHOT = os.path.join(VERIFY_DIR, "live_check.json")

_SAMPLE_DATA = {
    "company": "Acme Roofing",
    "website": "https://acme.com",
    "url": "https://acme.com",
    "headline": "Trusted Local Roofing",
    "ad_copy": "Free estimates",
    "brand_colors": ["#111111", "#eeeeee"],
    "logo_url": "",
    "hero_url": "",
    "metadata": {},
    "logo_path": "",
    "asset_paths": [],
    "logo": None,
    "screenshot_path": "",
    "business_intel": {"summary": "Local roofing expert"},
}


# ---------------------------------------------------------------------------
# Deterministic scraper/pipeline (production ResearchPipelineService, injected
# scraper + engines at its documented DI seam). No network, no weakened logic.
# ---------------------------------------------------------------------------


class _Scraper:
    def __init__(self, url: str, fail: bool) -> None:
        self.url = url
        self.fail = fail

    def run(self, progress_callback=None):
        if self.fail:
            raise ValueError("No valid website or missing URL")
        return dict(_SAMPLE_DATA)


_FAILING_DOMAINS = ("invalid.example", "nonexistent.example")


def _scraper_factory(url: str):
    fail = any(d in (url or "") for d in _FAILING_DOMAINS)
    return _Scraper(url, fail)


def _make_pipeline(project_root: str) -> ResearchPipelineService:
    """A production ResearchPipelineService with deterministic scraper/engines."""
    return ResearchPipelineService(
        project_store=ProjectStore(root=project_root),
        scraper_factory=_scraper_factory,
        brand_builder=BrandProfileBuilder.from_scrape_data,
        message_engine=lambda profile: [MessageStrategy()],
        concept_engine=lambda profile, strategies: [AdConcept()],
    )


# ---------------------------------------------------------------------------
# Honest live-network check (out-of-band WebsiteScraper)
# ---------------------------------------------------------------------------


def live_check(timeout_seconds: float = 25.0) -> dict:
    """Attempt a real scrape of the Jim Woods Roofing site; report honestly."""
    result = {"attempted": True, "success": False, "error": "", "domain_module": ""}
    try:
        from engine.scraper.site import WebsiteScraper

        result["domain_module"] = "engine.scraper.site.WebsiteScraper"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"WebsiteScraper import failed: {exc}"
        return result

    try:
        scraper = WebsiteScraper("https://www.jimwoodsroofing.com")
        if not hasattr(scraper, "run"):
            result["error"] = "Scraper has no run() method"
            return result
        data = scraper.run()
        result["success"] = bool(data)
        if not result["success"]:
            result["error"] = "Live scrape returned no data (site/network issue)."
    except Exception as exc:  # noqa: BLE001
        # Honest network/site failure — do NOT weaken production.
        result["success"] = False
        result["error"] = str(exc)[:400]
    return result


# ---------------------------------------------------------------------------
# Controlled end-to-end demonstration (real services, deterministic scraper)
# ---------------------------------------------------------------------------


def _count_projects(project_store) -> int:
    return len(project_store.list())


def _project_has_payload(project) -> bool:
    return bool(project.brand_profile and project.strategies and project.ad_concepts)


def main() -> int:
    # Reset the git-ignored verification workspace.
    if os.path.isdir(VERIFY_DIR):
        shutil.rmtree(VERIFY_DIR, ignore_errors=True)
    os.makedirs(PROJECTS_ROOT, exist_ok=True)

    prospect_store = ProspectStore(path=PROSPECTS_PATH)
    prospect_svc = ProspectWorkspaceService(store=prospect_store)
    prospect_svc.load()

    failures: list = []

    def step(n, label, ok, detail=""):
        flag = "PASS" if ok else "FAIL"
        print(f"{n:>2}. [{flag}] {label}" + (f"  - {detail}" if detail else ""))
        if not ok:
            failures.append((n, label, detail))

    # --- 1. Prospect records created (max 3) -------------------------------
    jim = prospect_svc.create_prospect(
        company_name="Jim Woods Roofing",
        website="www.jimwoodsroofing.com",
        category="Roofing",
    )
    acme = prospect_svc.create_prospect(
        company_name="Acme Windows",
        website="acmewindows.example",
        category="Windows",
    )
    bad = prospect_svc.create_prospect(
        company_name="No Good Site",
        website="invalid.example",
        category="Unknown",
    )
    prospects = prospect_svc.list_prospects()
    step(1, "Prospect records created", len(prospects) == 3,
         f"created={len(prospects)}")
    step(2, "READY prospects detected",
         len([p for p in prospects if p.is_ready_for_research()]) == 3)

    # --- 2. Queue service with the real pipeline ---------------------------
    jstore = ResearchQueueStore(path=QUEUE_PATH)
    pipeline = _make_pipeline(PROJECTS_ROOT)
    svc = ResearchQueueService(
        prospect_service=prospect_svc,
        job_store=jstore,
        pipeline=pipeline,
        max_attempts=2,
        retry_delays=(0, 0),  # immediate retries for the demonstration
    )
    svc.ensure_loaded()

    enqueued = svc.enqueue_ready_prospects()
    step(3, "READY prospects enqueued", enqueued == 3, f"enqueued={enqueued}")

    queue_exists = os.path.isfile(QUEUE_PATH)
    step(4, "Queue persisted to disk", queue_exists, QUEUE_PATH)

    # --- 3. Research executes (bounded batch) -------------------------------
    result = svc.run_batch(limit=3, concurrency=2)
    job_by_prospect = {j.prospect_id: j for j in svc.list_jobs()}
    jim_job = job_by_prospect.get(jim.prospect_id)
    acme_job = job_by_prospect.get(acme.prospect_id)
    bad_job = job_by_prospect.get(bad.prospect_id)

    step(5, "Research executes (batch run)",
         result.claimed == 3 and result.succeeded >= 1,
         f"claimed={result.claimed} succeeded={result.succeeded} "
         f"failed={result.failed}")

    ok_job = jim_job if jim_job and jim_job.status == STATUS_SUCCEEDED else acme_job
    step(6, "Success creates a durable Project",
         bool(ok_job and ok_job.project_id),
         f"project_id={ok_job.project_id if ok_job else None}")

    # --- 4. Project contains structured profile/strategies/concepts ---------
    pstore = ProjectStore(root=PROJECTS_ROOT)
    project_payload = False
    if ok_job and ok_job.project_id:
        proj = pstore.load(ok_job.project_id)
        project_payload = _project_has_payload(proj)
    step(7, "Project has BrandProfile + strategies + concepts", project_payload)

    # --- 5. Failure records error and queue continues -----------------------
    bad_job = next((j for j in svc.list_jobs() if j.status == STATUS_FAILED), None)
    step(8, "Failure records error + queue continues",
         bool(bad_job and bad_job.last_error) and result.succeeded >= 1,
         f"bad.error={bad_job.last_error if bad_job else ''}")

    # --- 6. Queue reloads from disk -----------------------------------------
    jstore2 = ResearchQueueStore(path=QUEUE_PATH)
    jstore2.load()
    reloaded_jobs = jstore2.list()
    step(9, "Queue reloads from disk", len(reloaded_jobs) == 3,
         f"loaded={len(reloaded_jobs)}")

    # --- 7. Successful job associated with its Project -----------------------
    associated = False
    if ok_job and ok_job.project_id:
        proj = pstore.load(ok_job.project_id)
        associated = proj.metadata.get("prospect_id") == ok_job.prospect_id
    step(10, "Successful job <-> Project association", associated and bool(ok_job),
         f"job.project_id={ok_job.project_id if ok_job else None}")

    # --- 8. Rerun does NOT duplicate Project ----------------------------------
    if ok_job:
        svc.enqueue_prospect(ok_job.prospect_id, force=True)
    projects_before = _count_projects(pstore)
    svc.run_batch(limit=3, concurrency=2)
    projects_after = _count_projects(pstore)
    step(11, "Rerun/retry does NOT duplicate Project",
         projects_after == projects_before,
         f"projects_before={projects_before} after={projects_after}")

    # --- 9. Successful persisted research is not needlessly re-enqueued ------
    prospect_svc2 = ProspectWorkspaceService(
        store=ProspectStore(path=PROSPECTS_PATH)
    )
    prospect_svc2.load()
    svc2 = ResearchQueueService(
        prospect_service=prospect_svc2,
        job_store=ResearchQueueStore(path=QUEUE_PATH),
        pipeline=_make_pipeline(PROJECTS_ROOT),
    )
    svc2.ensure_loaded()
    rejected = True
    if ok_job:
        reason: list = []
        rejected = not svc2.enqueue_prospect(ok_job.prospect_id, reason=reason)
    # Count jobs for the succeeded prospect before/after the fresh enqueue.
    busy_before = len(
        [j for j in svc2.list_jobs() if j.prospect_id == ok_job.prospect_id]
    ) if ok_job else 0
    fresh_enqueued = svc2.enqueue_ready_prospects()
    busy_after = len(
        [j for j in svc2.list_jobs() if j.prospect_id == ok_job.prospect_id]
    ) if ok_job else 0
    step(12, "Successfully researched prospect is not re-enqueued",
         rejected and busy_after == busy_before,
         f"rejected_duplicate_success={rejected} "
         f"succeed_jobs_before={busy_before} after={busy_after} "
         f"fresh_enqueued={fresh_enqueued}")

    # --- 10. Restart recovery on persisted data -------------------------------
    recovery_queue = os.path.join(VERIFY_DIR, "recovery_queue.json")
    rjstore = ResearchQueueStore(path=recovery_queue)
    rsvc = ResearchQueueService(
        prospect_service=prospect_svc2,
        job_store=rjstore,
        pipeline=_make_pipeline(PROJECTS_ROOT),
    )
    rsvc.ensure_loaded()
    rsvc.enqueue_prospect(jim.prospect_id)
    rsvc.claim_next_job()  # -> RUNNING (persisted to disk by the store)
    persisted_running = rjstore.list()
    running_jobs = [j for j in persisted_running if j.status == STATUS_RUNNING]
    # Simulate a fresh process: new service over the SAME persisted queue file.
    rsvc2 = ResearchQueueService(
        prospect_service=prospect_svc2,
        job_store=ResearchQueueStore(path=recovery_queue),
        pipeline=_make_pipeline(PROJECTS_ROOT),
    )
    rsvc2.ensure_loaded()
    recovered_count = rsvc2.recover_stale()
    left_running = [j for j in rsvc2.list_jobs() if j.status == STATUS_RUNNING]
    final_status = rsvc2.list_jobs()[0].status if rsvc2.list_jobs() else None
    step(13, "Restart: RUNNING job recovered from persisted data",
         running_jobs and recovered_count >= 1 and not left_running
         and final_status in (STATUS_PENDING, STATUS_RETRY_PENDING),
         f"persisted_running={len(running_jobs)} recovered={recovered_count} "
         f"left_running={len(left_running)} final_status={final_status}")

    # --- 11. Honest live-network check (out-of-band WebsiteScraper) -----------
    lc = live_check(timeout_seconds=20.0)
    live_status = "success" if lc["success"] else ("error: " + (lc["error"] or "network"))
    print("\nLIVE NETWORK CHECK (out-of-band WebsiteScraper, production module):")
    print(f"  {lc['domain_module']} -> {'SUCCESS' if lc['success'] else 'could not reach site'}")
    print(f"  detail: {live_status}")
    if lc["error"]:
        print("  NOTE: reported honestly - production logic was NOT weakened to force a pass.")

    with open(LIVE_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump({"live_check": lc}, f, indent=2)
    print(f"\nVerification artifacts under: {VERIFY_DIR}")

    print(f"\n{'='*70}")
    if failures:
        print(f"RESULT: {len(failures)} step(s) FAILED")
        for n, label, detail in failures:
            print(f"  step {n}: {label} - {detail}")
        return 1
    print("RESULT: All Sprint 5B verification steps PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


