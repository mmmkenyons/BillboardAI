#!/usr/bin/env python
"""Sprint 5J verifier — Prospect batch mockup generation foundation."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5j_verify_")
    print(f"VERIFIER ROOT: {root}")
    print("SYNTHETIC VERIFICATION DATA\n")

    from gui.models.mockup_result import MockupResult
    from gui.models.project_store import ProjectStore
    from gui.models.prospect import Prospect
    from gui.models.prospect_generation import JOB_STATUS_FAILED, JOB_STATUS_QUEUED, JOB_STATUS_SUCCEEDED
    from gui.models.prospect_generation_store import ProspectGenerationStore
    from gui.models.prospect_store import ProspectStore
    from gui.services.prospect_generation import ProspectGenerationService

    passed = 0
    failed = 0

    def check(name: str, condition: bool, message: str = "") -> None:
        nonlocal passed, failed
        if condition:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}: {message}")
            failed += 1

    prospect_store = ProspectStore(path=os.path.join(root, "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
    project_store = ProjectStore(root=os.path.join(root, "projects"))
    for prospect in [
        Prospect(prospect_id="a", company_name="ABC Roofing", website="https://abc.com", category="roofing"),
        Prospect(prospect_id="b", company_name="XYZ Dental", website="https://xyz.com", category="dentist"),
        Prospect(prospect_id="c", company_name="NoSite LLC", website="", category="roofing"),
        Prospect(prospect_id="d", company_name="Manual Template", website="https://manual.com", category="unknown"),
    ]:
        prospect_store.create(prospect)
    prospect_store.save()

    calls: list[str] = []

    def fake_generate(request):
        calls.append(request.url)
        if request.url.endswith("xyz.com"):
            raise RuntimeError("render failed")
        return MockupResult(
            success=True,
            website=request.url,
            output_path=request.output_path,
            preview_path=request.output_path,
            company_name="Done Co",
            extra={"render_context": {"company_name": "Done Co", "headline": "Hi", "cta": "Call", "template": request.template, "source_url": request.url, "logo_image": "", "hero_image": "", "background_image": request.output_path}},
        )

    service = ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
        generation_callable=fake_generate,
        default_output_root=os.path.join(root, "projects"),
    )

    e_a = service.check_eligibility("a")
    e_b = service.check_eligibility("b")
    e_c = service.check_eligibility("c")
    e_d = service.check_eligibility("d")
    e_d_manual = service.check_eligibility("d", template="contractor")
    e_missing = service.check_eligibility("missing")
    check("Eligible contractor prospect", e_a.eligible and e_a.resolved_template == "contractor")
    check("Eligible dentist prospect", e_b.eligible and e_b.resolved_template == "dentist")
    check("Missing website rejected", (not e_c.eligible) and "Missing website" in e_c.reasons)
    check("Unknown category rejected without override", (not e_d.eligible) and "No supported template" in e_d.reasons)
    check("Explicit template override works", e_d_manual.eligible and e_d_manual.resolved_template == "contractor")
    check("Missing prospect rejected", (not e_missing.eligible) and "Prospect not found" in e_missing.reasons)

    before = prospect_store.get("a").to_dict()
    service.check_eligibility("a")
    after = prospect_store.get("a").to_dict()
    check("Eligibility is non-mutating", before == after)
    check("Eligibility does not generate", calls == [])
    check("Eligibility does not create projects", project_store.list() == [])

    created = service.create_jobs(["a", "b", "c", "d"], templates={"d": "contractor"})
    check("Mixed batch returns 4 results", len(created) == 4)
    check("A queued", created[0].job is not None and created[0].job.status == JOB_STATUS_QUEUED)
    check("B queued", created[1].job is not None and created[1].job.status == JOB_STATUS_QUEUED)
    check("C rejected", created[2].job is None and not created[2].eligible)
    check("D queued with manual template", created[3].job is not None and created[3].job.template == "contractor")
    check("Queueing does not create projects", project_store.list() == [])

    dup = service.create_job("a")
    check("Duplicate active job blocked", (not dup.eligible) and "Active job already exists" in dup.reasons)

    check("Three jobs persisted", len(service.list_jobs()) == 3)
    reloaded_jobs = ProspectGenerationStore(path=job_store.path).list()
    check("Reload preserves queued jobs", len(reloaded_jobs) == 3)

    run_results = service.run_queue()
    status_map = {job.prospect_id: job.status for job in run_results}
    check("A success", status_map.get("a") == JOB_STATUS_SUCCEEDED)
    check("B failure", status_map.get("b") == JOB_STATUS_FAILED)
    check("D success", status_map.get("d") == JOB_STATUS_SUCCEEDED)
    check("Queue continues after failure", len(run_results) == 3)
    check("Generation invoked sequentially", calls == ["https://abc.com", "https://xyz.com", "https://manual.com"])
    check("Projects created only at run time", len(project_store.list()) == 3)

    a = prospect_store.get("a")
    b = prospect_store.get("b")
    d = prospect_store.get("d")
    check("Success associates project_id on A", a is not None and bool(a.metadata.get("project_id")))
    check("Failure does not associate project_id on B", b is not None and not b.metadata.get("project_id"))
    check("Manual-template success associates project_id on D", d is not None and bool(d.metadata.get("project_id")))
    check("Result path stored on A", a is not None and bool(a.metadata.get("generation_result_path")))

    a_project_id = str(a.metadata.get("project_id") or "") if a is not None else ""
    d_project_id = str(d.metadata.get("project_id") or "") if d is not None else ""
    a_project = project_store.load(a_project_id)
    d_project = project_store.load(d_project_id)
    check("Project A prospect metadata correct", a_project.metadata.get("prospect_id") == "a")
    check("Project D prospect metadata correct", d_project.metadata.get("prospect_id") == "d")
    check("Prospect A project exists in ProjectStore", project_store.exists(a_project_id))
    check("Prospect D project exists in ProjectStore", project_store.exists(d_project_id))

    saved_project_id = a_project_id
    service2 = ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
        generation_callable=lambda _request: (_ for _ in ()).throw(RuntimeError("boom")),
        default_output_root=os.path.join(root, "projects"),
    )
    rerun = service2.create_job("a")
    rerun_job = service2.run_job(rerun.job.id)
    check("Completed job may regenerate", rerun.job is not None)
    check("Raised exception records FAILED", rerun_job.status == JOB_STATUS_FAILED and bool(rerun_job.error))
    check("Failed rerun preserves prior project link", prospect_store.get("a").metadata.get("project_id") == saved_project_id)

    restarted = ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=ProspectGenerationStore(path=job_store.path),
        project_store=project_store,
        generation_callable=fake_generate,
        default_output_root=os.path.join(root, "projects"),
    )
    project_ids_before_browse = {project.id for project in project_store.list()}
    job_ids_after_restart = {job.id for job in restarted.list_jobs()}
    _ = restarted.check_eligibility("a")
    _ = restarted.check_eligibility("d", template="contractor")
    _ = restarted.jobs_for_prospect("a")
    _ = restarted.jobs_for_prospect("d")
    project_ids_after_browse = {project.id for project in project_store.list()}
    check("Restart preserves jobs", len(restarted.list_jobs()) >= 4)
    check("Restart preserves job ids", len(job_ids_after_restart) >= 4)
    check("Restart preserves prospects", restarted.prospect_store.get("a") is not None)
    check("Generated projects remain intact after restart", a_project_id in project_ids_after_browse and d_project_id in project_ids_after_browse)
    check(
        "No browse-time project creation after restart",
        project_ids_before_browse == project_ids_after_browse,
        f"before={sorted(project_ids_before_browse)} after={sorted(project_ids_after_browse)}",
    )

    print()
    print("=" * 60)
    print("SPRINT 5J VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Temp data at: {root}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(verify())