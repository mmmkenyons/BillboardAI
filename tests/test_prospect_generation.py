from __future__ import annotations

import os

from gui.models.mockup_result import MockupResult
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.prospect_generation import ProspectGenerationService


def _stores(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    return prospect_store, job_store, project_store


def _seed_prospect(store: ProspectStore, **overrides):
    prospect = Prospect(
        prospect_id=overrides.pop("prospect_id", "p1"),
        company_name=overrides.pop("company_name", "ABC Roofing"),
        website=overrides.pop("website", "https://abc.com"),
        category=overrides.pop("category", "roofing"),
        **overrides,
    )
    store.create(prospect)
    store.save()
    return prospect


def test_eligibility_valid(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store)
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    result = service.check_eligibility(prospect.prospect_id)
    assert result.eligible is True
    assert result.resolved_template == "contractor"


def test_eligibility_missing_prospect(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    result = service.check_eligibility("missing")
    assert result.eligible is False
    assert "Prospect not found" in result.reasons


def test_eligibility_missing_website(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store, website="")
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    result = service.check_eligibility(prospect.prospect_id)
    assert result.eligible is True
    assert "Missing website" not in result.reasons


def test_eligibility_missing_website_and_no_canonical_intelligence(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store, website="", category="")
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    result = service.check_eligibility(prospect.prospect_id)
    assert result.eligible is False
    assert "Missing website" in result.reasons


def test_eligibility_unsupported_template(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store, category="unknown")
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    result = service.check_eligibility(prospect.prospect_id)
    assert result.eligible is False
    assert "No supported template" in result.reasons


def test_job_persistence_and_updates(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store)
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    created = service.create_job(prospect.prospect_id)
    assert created.job is not None
    assert created.job.status == JOB_STATUS_QUEUED
    assert project_store.list() == []
    reloaded = ProspectGenerationStore(path=job_store.path)
    assert len(reloaded.list()) == 1
    job = reloaded.list()[0]
    job.status = JOB_STATUS_RUNNING
    reloaded.upsert(job)
    reloaded.save()
    again = ProspectGenerationStore(path=job_store.path)
    assert again.list()[0].status == JOB_STATUS_RUNNING


def test_duplicate_active_job_blocked(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store)
    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    first = service.create_job(prospect.prospect_id)
    assert first.eligible is True
    second = service.create_job(prospect.prospect_id)
    assert second.eligible is False
    assert "Active job already exists" in second.reasons


def test_completed_job_can_regenerate(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store)

    def fake_generate(_request):
        return MockupResult(success=True, website=prospect.website, output_path="out.png", preview_path="out.png")

    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, generation_callable=fake_generate, default_output_root=str(tmp_path), project_store=project_store)
    first = service.create_job(prospect.prospect_id)
    service.run_job(first.job.id)
    second = service.create_job(prospect.prospect_id)
    assert second.eligible is True


def test_success_associates_correct_prospect(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect_a = _seed_prospect(prospect_store, prospect_id="a", company_name="A Co", website="https://a.com")
    _seed_prospect(prospect_store, prospect_id="b", company_name="B Co", website="https://b.com")

    def fake_generate(request):
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path, company_name="A Co")

    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, generation_callable=fake_generate, default_output_root=str(tmp_path), project_store=project_store)
    created = service.create_job(prospect_a.prospect_id)
    job = service.run_job(created.job.id)
    assert job.status == JOB_STATUS_SUCCEEDED
    updated_a = prospect_store.get("a")
    updated_b = prospect_store.get("b")
    assert updated_a is not None and updated_a.metadata.get("project_id")
    assert updated_b is not None and not updated_b.metadata.get("project_id")


def test_generation_request_carries_person_context(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(
        prospect_store,
        contact_name="Jane Smith",
        contact_title="Agent",
        resolved_profile_url="https://example.com/agent/jane-smith/",
        resolution_status="RESOLVED",
        resolution_confidence="HIGH",
        category="real estate",
    )
    seen = {}

    def fake_generate(request):
        seen.update(request.options.get("person_context") or {})
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, generation_callable=fake_generate, default_output_root=str(tmp_path), project_store=project_store)
    created = service.create_job(prospect.prospect_id)
    service.run_job(created.job.id)
    assert seen["contact_name"] == "Jane Smith"
    assert seen["resolved_profile_url"] == "https://example.com/agent/jane-smith/"


def test_failure_does_not_overwrite_prior_success(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect = _seed_prospect(prospect_store)

    def ok_generate(request):
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, generation_callable=ok_generate, default_output_root=str(tmp_path), project_store=project_store)
    first = service.create_job(prospect.prospect_id)
    service.run_job(first.job.id)
    saved_project_id = prospect_store.get(prospect.prospect_id).metadata.get("project_id")

    def bad_generate(_request):
        raise RuntimeError("boom")

    failing = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, generation_callable=bad_generate, default_output_root=str(tmp_path), project_store=project_store)
    second = failing.create_job(prospect.prospect_id)
    result = failing.run_job(second.job.id)
    assert result.status == JOB_STATUS_FAILED
    assert prospect_store.get(prospect.prospect_id).metadata.get("project_id") == saved_project_id


def test_queue_continues_after_failure(tmp_path) -> None:
    prospect_store, job_store, project_store = _stores(tmp_path)
    _seed_prospect(prospect_store, prospect_id="a", website="https://a.com")
    _seed_prospect(prospect_store, prospect_id="b", website="https://b.com")
    _seed_prospect(prospect_store, prospect_id="c", website="https://c.com")

    def fake_generate(request):
        if request.url.endswith("b.com"):
            raise RuntimeError("fail b")
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    service = ProspectGenerationService(prospect_store=prospect_store, job_store=job_store, generation_callable=fake_generate, default_output_root=str(tmp_path), project_store=project_store)
    ids = [r.job.id for r in service.create_jobs(["a", "b", "c"]) if r.job is not None]
    results = [service.run_job(job_id).status for job_id in ids]
    assert results == [JOB_STATUS_SUCCEEDED, JOB_STATUS_FAILED, JOB_STATUS_SUCCEEDED]