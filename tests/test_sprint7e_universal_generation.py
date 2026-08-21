from __future__ import annotations

import os

from engine.brand_profile import BrandProfileBuilder
from gui.engine_bridge import generate
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.models.prospect import Prospect
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.project_store import ProjectStore
from gui.models.render_context import RenderContext
from gui.services.canonical_prospect_intelligence import canonical_context, merge_canonical_with_scrape, select_creative_phone
from gui.services.prospect_generation import GENERIC_TEMPLATE, ProspectGenerationService


def _stores(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    return prospect_store, job_store, project_store


def _prospect(**overrides) -> Prospect:
    base = dict(
        prospect_id="p1",
        company_name="Generic Business LLC",
        company_name_for_ads="Generic Business",
        website="https://generic.example",
        company_phone="6125550100",
        mobile_phone="6125550111",
        city="Minneapolis",
        state="MN",
        email="owner@generic.example",
        metadata={"field_provenance": {"company_name_for_ads": {"origin": "IMPORTED", "source_column": "Display"}}},
    )
    base.update(overrides)
    return Prospect(**base)


def _service_with(p: Prospect, tmp_path, fake_generate=None):
    prospect_store, job_store, project_store = _stores(tmp_path)
    prospect_store.create(p)
    prospect_store.save()
    return ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
        generation_callable=fake_generate,
        default_output_root=str(tmp_path),
    )


def test_explicit_templates_preserved(tmp_path) -> None:
    cases = [
        (_prospect(prospect_id="contractor", category="roofing", naics_codes=["238160"]), "contractor"),
        (_prospect(prospect_id="dentist", category="dental", company_keywords=["family dentist"]), "dentist"),
        (_prospect(prospect_id="realtor", category="real estate", company_keywords=["realtor"]), "realtor"),
    ]
    for prospect, expected in cases:
        service = _service_with(prospect, tmp_path / prospect.prospect_id)
        eligibility = service.check_eligibility(prospect.prospect_id)
        assert eligibility.eligible is True
        assert eligibility.resolved_template == expected
        created = service.create_job(prospect.prospect_id)
        assert created.job is not None
        assert created.job.metadata["template_selection"]["generic_fallback_used"] is False


def test_generic_fallback_verticals_create_jobs(tmp_path) -> None:
    cases = [
        _prospect(prospect_id="landscaping", company_name_for_ads="Urban Green Landscapes", naics_codes=["561730"], industry="Landscaping"),
        _prospect(prospect_id="solar", company_name_for_ads="Odd Header Solar", company_keywords=["solar installation", "solar energy"]),
        _prospect(prospect_id="bakery", company_name_for_ads="Neighborhood Cakes", naics_codes=["311811"], industry="Bakery"),
        _prospect(prospect_id="moving", company_name_for_ads="North Loop Movers", company_keywords=["moving", "logistics"]),
    ]
    for prospect in cases:
        service = _service_with(prospect, tmp_path / prospect.prospect_id)
        eligibility = service.check_eligibility(prospect.prospect_id)
        assert eligibility.eligible is True
        assert eligibility.resolved_template == GENERIC_TEMPLATE
        created = service.create_job(prospect.prospect_id)
        assert created.job is not None
        assert created.job.template == GENERIC_TEMPLATE
        assert created.job.metadata["template_selection"]["generic_fallback_reason"] == "GENERIC_FALLBACK_ELIGIBLE"


def test_minimal_company_location_only_remains_blocked(tmp_path) -> None:
    p = _prospect(website="", company_phone="", mobile_phone="", naics_codes=[], company_keywords=[], industry="", category="", city="Minneapolis", state="MN")
    service = _service_with(p, tmp_path)
    eligibility = service.check_eligibility(p.prospect_id)
    assert eligibility.eligible is False
    assert "GENERIC_FALLBACK_INSUFFICIENT_INTELLIGENCE" in eligibility.reasons
    assert service.create_job(p.prospect_id).job is None


def test_blank_website_generic_generation_path_reachable(tmp_path) -> None:
    seen = {}

    def fake_generate(request):
        seen["url"] = request.url
        seen["template"] = request.template
        seen["options"] = dict(request.options)
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path, company_name="Urban Green")

    p = _prospect(website="", domain="", company_name_for_ads="Urban Green", naics_codes=["561730"])
    service = _service_with(p, tmp_path, fake_generate=fake_generate)
    created = service.create_job(p.prospect_id)
    assert created.job is not None
    ran = service.run_job(created.job.id)
    assert ran.status == "SUCCEEDED"
    assert seen["url"] == ""
    assert seen["template"] == GENERIC_TEMPLATE
    assert seen["options"]["generation_template_selection"]["generic_fallback_used"] is True


def test_challenge_content_suppressed_for_generic_context() -> None:
    p = _prospect(company_name_for_ads="Odd Header Solar", company_keywords=["solar installation"])
    merged = merge_canonical_with_scrape(
        {"company": "Please Verify You Are Human", "headline": "Checking your browser", "ad_copy": "CAPTCHA required", "metadata": {"title": "Access denied"}},
        canonical_context(p),
    )
    profile = BrandProfileBuilder.from_scrape_data(merged)
    ctx = RenderContext.from_brand_profile(profile, template=GENERIC_TEMPLATE)
    assert profile.company_name == "Odd Header Solar"
    assert "Verify" not in ctx.company_name
    assert "CAPTCHA" not in ctx.headline
    assert ctx.opportunity_context["generic_fallback_policy"]["code"] == "GENERIC_FALLBACK_ELIGIBLE"


def test_display_company_unresolved_person_email_and_phone_preserved(tmp_path, monkeypatch) -> None:
    p = _prospect(
        company_name="T2 Roofing LLC",
        company_name_for_ads="T2 Roofing",
        company_phone="3035550199",
        mobile_phone="3035550101",
        email="existing@example.com",
        resolution_status="NOT_FOUND",
        contact_name="Jane Smith",
        contact_title="Owner",
        company_keywords=["landscaping"],
    )
    assert select_creative_phone(p)["phone"] == "3035550199"
    out = str(tmp_path / "generic.png")
    monkeypatch.setattr("gui.engine_bridge.render_billboard", lambda spec, output_path: output_path)
    result = generate(MockupRequest(url="", template=GENERIC_TEMPLATE, output_path=out, options={"allow_canonical_fallback": True, "canonical_prospect_intelligence": canonical_context(p), "generation_template_selection": {"generic_fallback_used": True}}))
    assert result.success is True
    assert result.company_name == "T2 Roofing"
    assert result.extra["render_context"]["selected_phone"] == "3035550199"
    assert result.extra["render_context"]["opportunity_context"]["person_facts"]["contact_name"] == ""
    assert p.email == "existing@example.com"


def test_blank_email_does_not_block_generic_generation(tmp_path) -> None:
    p = _prospect(email="", company_keywords=["bakery"])
    service = _service_with(p, tmp_path, fake_generate=lambda request: MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path))
    created = service.create_job(p.prospect_id)
    assert created.job is not None
    assert service.run_job(created.job.id).status == "SUCCEEDED"