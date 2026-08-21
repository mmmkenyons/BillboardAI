from __future__ import annotations

import os

from engine.brand_profile import BrandProfileBuilder
from gui.engine_bridge import build_render_context, generate
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.models.prospect import Prospect
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.project_store import ProjectStore
from gui.models.render_context import RenderContext
from gui.services.canonical_prospect_intelligence import (
    business_classification,
    canonical_context,
    has_generation_intelligence,
    merge_canonical_with_scrape,
    preferred_display_company_name,
    select_creative_phone,
)
from gui.services.prospect_generation import ProspectGenerationService


def _prospect(**overrides) -> Prospect:
    base = dict(
        prospect_id="p1",
        company_name="T2 Roofing LLC",
        company_name_for_ads="T2 Roofing",
        website="https://t2roofing.example",
        company_phone="3035550199",
        mobile_phone="3035550101",
        work_direct_phone="3035550202",
        city="Denver",
        state="CO",
        naics_codes=["238160"],
        company_keywords=["roof repair", "residential roofing", "storm damage"],
        industry="Construction",
        email="ana@t2roof.example",
        metadata={
            "field_provenance": {
                "company_name": {"origin": "IMPORTED", "source_column": "Company name"},
                "company_name_for_ads": {"origin": "IMPORTED", "source_column": "Company name for emails"},
                "company_phone": {"origin": "IMPORTED", "source_column": "Corporate phone"},
                "naics_codes": {"origin": "IMPORTED", "source_column": "NAICS codes"},
            },
            "email_state": {"status": "email_present", "email_enrichment_eligible": False},
        },
    )
    base.update(overrides)
    return Prospect(**base)


def test_creative_company_name_preference_and_legal_preservation() -> None:
    p = _prospect()
    assert preferred_display_company_name(p) == "T2 Roofing"
    assert p.company_name == "T2 Roofing LLC"
    ctx = canonical_context(p)
    assert ctx["display_company_name"] == "T2 Roofing"
    assert ctx["legal_company_name"] == "T2 Roofing LLC"
    assert ctx["company_name"]["source_field"] == "company_name_for_ads"


def test_phone_ranking_provenance_and_alternatives() -> None:
    p = _prospect(other_phone="3035557777")
    selected = select_creative_phone(p, website_phone="3035558888")
    assert selected["phone"] == "3035550199"
    assert selected["source_field"] == "company_phone"
    assert selected["origin"] == "IMPORTED"
    assert any(a["source_field"] == "mobile_phone" for a in selected["alternatives"])


def test_classification_naics_keywords_industry_hierarchy() -> None:
    p = _prospect()
    evidence = business_classification(p)
    assert evidence["basis"] == "naics_codes"
    assert evidence["label"] == "Roofing Contractors"
    assert "storm damage" in evidence["keywords"]
    assert evidence["label"] != "Construction"


def test_website_optional_generation_eligibility_and_request_context(tmp_path) -> None:
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    p = _prospect(website="", domain="")
    store.create(p)
    jobs = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    projects = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    seen = {}

    def fake_generate(request):
        seen.update(request.options)
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path, company_name="T2 Roofing")

    service = ProspectGenerationService(prospect_store=store, job_store=jobs, project_store=projects, generation_callable=fake_generate, default_output_root=str(tmp_path))
    eligibility = service.check_eligibility(p.prospect_id)
    assert eligibility.eligible is True
    created = service.create_job(p.prospect_id)
    assert created.job is not None
    assert created.job.website == ""
    service.run_job(created.job.id)
    assert seen["allow_canonical_fallback"] is True
    assert seen["canonical_prospect_intelligence"]["display_company_name"] == "T2 Roofing"


def test_imported_brand_profile_fallback_and_render_context_propagation() -> None:
    p = _prospect(website="")
    data = merge_canonical_with_scrape({}, canonical_context(p))
    profile = BrandProfileBuilder.from_scrape_data(data)
    assert profile.company_name == "T2 Roofing"
    assert profile.phone == "3035550199"
    assert profile.logo is None
    ctx = RenderContext.from_brand_profile(profile)
    assert ctx.company_name == "T2 Roofing"
    assert ctx.selected_phone == "3035550199"
    assert ctx.business_classification == "Roofing Contractors"
    assert ctx.location == "Denver, CO"
    assert ctx.opportunity_context["canonical_prospect_intelligence"]["legal_company_name"] == "T2 Roofing LLC"


def test_challenge_page_suppression_with_canonical_fallback() -> None:
    p = _prospect()
    scraped = {
        "url": "https://t2roofing.example",
        "company": "Please Verify You Are Human",
        "headline": "Checking your browser",
        "ad_copy": "captcha required",
        "metadata": {"title": "Verify human"},
    }
    merged = merge_canonical_with_scrape(scraped, canonical_context(p))
    profile = BrandProfileBuilder.from_scrape_data(merged)
    assert profile.company_name == "T2 Roofing"
    assert profile.headline == ""
    assert profile.ad_copy == ""
    assert profile.phone == "3035550199"
    assert profile.categories[0] == "Roofing Contractors"
    assert "Verify" not in RenderContext.from_brand_profile(profile).headline


def test_render_context_serialization_reload_preserves_canonical_fields() -> None:
    p = _prospect()
    profile = BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(p)))
    ctx = RenderContext.from_brand_profile(profile)
    reloaded = RenderContext.from_dict(ctx.to_dict())
    assert reloaded.selected_phone == "3035550199"
    assert reloaded.business_classification == "Roofing Contractors"
    assert reloaded.location == "Denver, CO"
    assert reloaded.opportunity_context["creative_phone_source"] == "company_phone"


def test_minimal_generic_csv_compatibility_and_blank_email() -> None:
    p = _prospect(company_name="Minimal Co", company_name_for_ads="", website="", domain="", company_phone="", mobile_phone="", work_direct_phone="", naics_codes=[], company_keywords=[], industry="", city="Sioux Falls", state="SD", email="", metadata={})
    assert p.company_name == "Minimal Co"
    assert p.email == ""
    assert canonical_context(p)["email_state"]["email_enrichment_eligible"] is True
    assert has_generation_intelligence(p) is True


def test_imported_contact_unresolved_profile_does_not_promote_identity() -> None:
    p = _prospect(contact_name="Jane Smith", contact_title="Owner", resolution_status="NOT_FOUND", resolved_profile_url="", manual_profile_url="")
    data = merge_canonical_with_scrape({}, canonical_context(p))
    profile = BrandProfileBuilder.from_scrape_data(data)
    assert profile.person_facts.contact_name == ""
    assert profile.personalized_headline == ""
    ctx = RenderContext.from_brand_profile(profile)
    assert ctx.opportunity_context["person_facts"]["contact_name"] == ""


def test_engine_bridge_no_website_canonical_fallback(monkeypatch, tmp_path) -> None:
    p = _prospect(website="")
    out = str(tmp_path / "out.png")
    monkeypatch.setattr("gui.engine_bridge.render_billboard", lambda spec, output_path: output_path)
    result = generate(MockupRequest(url="", template="contractor", output_path=out, options={"allow_canonical_fallback": True, "canonical_prospect_intelligence": canonical_context(p)}))
    assert result.success is True
    assert result.company_name == "T2 Roofing"
    assert result.extra["brand_profile"]["source_metadata"]["canonical_fallback_used"] is True
    assert result.extra["render_context"]["selected_phone"] == "3035550199"


def test_build_render_context_accepts_merged_canonical_data() -> None:
    p = _prospect()
    rc = build_render_context(merge_canonical_with_scrape({"url": p.website, "company": "Scraped T2"}, canonical_context(p)), template="contractor", source_url=p.website)
    assert rc["company_name"] == "T2 Roofing"
    assert rc["selected_phone"] == "3035550199"
    assert rc["business_classification"] == "Roofing Contractors"