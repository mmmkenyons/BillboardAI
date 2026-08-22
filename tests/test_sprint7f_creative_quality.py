from __future__ import annotations

import json

from engine.brand_profile import BrandProfileBuilder
from engine.renderer.renderer import RENDER_CTA_OVERFLOW, RENDER_HEADLINE_OVERFLOW, RENDER_QUALITY_BLOCKED, RENDER_QUALITY_PASS, RENDER_TEXT_CLIPPED, get_last_render_quality, render_billboard
from gui.models.mockup_concept import MockupConcept
from gui.models.project import Project
from gui.models.prospect import Prospect
from gui.models.render_context import RenderContext
from gui.services.copy_quality import PERSON_MATCH, PERSON_MISMATCH, PERSON_NAME_MISMATCH, PERSON_NOT_REFERENCED, QUALITY_BLOCKED, QUALITY_PASS, assess_copy_quality, classify_person_identity


class _Row:
    def __init__(self, headline: str, cta: str = "Call Today", body: str = "") -> None:
        self.headline = headline
        self.cta = cta
        self.email_subject = ""
        self.email_body = body


def _render(tmp_path, *, headline: str, cta: str = "Call Today", template: str = "contractor", opportunity_context: dict | None = None) -> dict:
    spec = RenderContext(company_name="Example Co", headline=headline, cta=cta, template=template, opportunity_context=opportunity_context or {}).to_render_spec()
    render_billboard(spec, str(tmp_path / f"{template}_{abs(hash((headline, cta))) % 100000}.png"))
    return get_last_render_quality()


def _codes(quality: dict) -> set[str]:
    return {str(r.get("code")) for r in quality.get("reasons") or []}


def _copy_result(headline: str, *, contact_name: str = "Julia Harbor", company: str = "Harbor Realty"):
    prospect = Prospect(prospect_id="p1", company_name=company, website="https://example.test", email="a@example.test", contact_name=contact_name)
    concept = MockupConcept.create("mock.png", "realtor", headline, "Let's Talk", 90, company_name=company)
    return assess_copy_quality(prospect=prospect, concept=concept, project=Project(company=company), row=_Row(headline=headline, cta="Let's Talk"))


def test_case_a_headline_fits_normally_without_adjustment(tmp_path) -> None:
    quality = _render(tmp_path, headline="Trusted Local Roofing")
    assert quality["status"] == RENDER_QUALITY_PASS
    assert RENDER_TEXT_CLIPPED not in _codes(quality)
    assert quality["diagnostics"]["headline_fit_adjusted"] is False


def test_case_b_slightly_long_headline_gets_bounded_fit(tmp_path) -> None:
    quality = _render(tmp_path, headline="Commercial real estate and leasing in Portland.", template="realtor")
    assert quality["status"] == RENDER_QUALITY_PASS
    assert RENDER_TEXT_CLIPPED not in _codes(quality)
    diag = quality["diagnostics"]
    assert diag["headline_fit_adjusted"] is True
    assert diag["headline_font_size_used"] >= 24


def test_case_c_very_long_impossible_headline_still_blocks(tmp_path) -> None:
    quality = _render(tmp_path, headline="X" * 300)
    assert quality["status"] == RENDER_QUALITY_BLOCKED
    assert {RENDER_HEADLINE_OVERFLOW, RENDER_TEXT_CLIPPED} & _codes(quality)


def test_case_d_cta_fit_adjustment(tmp_path) -> None:
    quality = _render(tmp_path, headline="Dental Care In Aurora", cta="Schedule Your Visit")
    assert RENDER_CTA_OVERFLOW not in _codes(quality)
    assert quality["diagnostics"]["cta_font_size_used"] >= 14


def test_case_e_minimum_font_prevents_unreadable_shrinking(tmp_path) -> None:
    quality = _render(tmp_path, headline="Unbreakable" * 40)
    assert quality["status"] == RENDER_QUALITY_BLOCKED
    assert quality["diagnostics"]["headline_font_size_used"] >= 24


def test_semantic_shortening_remediates_7d_dental_equivalent(tmp_path) -> None:
    quality = _render(tmp_path, headline="Cosmetic and family dentistry in Aurora. Email smiles@clearwaterdentalco.com", cta="Call 7205552200", template="dentist")
    assert quality["status"] == RENDER_QUALITY_PASS
    assert RENDER_TEXT_CLIPPED not in _codes(quality)
    assert quality["diagnostics"]["headline_fit_adjusted"] is True
    assert quality["diagnostics"]["headline_font_size_used"] >= 24


def test_case_l_generic_template_long_category_safely_handled(tmp_path) -> None:
    opportunity = {"canonical_prospect_intelligence": {"classification": {"label": "Professional Residential Landscaping Services", "keywords": ["Residential Landscaping"]}}}
    quality = _render(tmp_path, headline="Professional Residential Landscaping Services With Seasonal Maintenance Planning", template="generic", opportunity_context=opportunity)
    assert quality["diagnostics"]["headline_font_size_used"] >= 24
    assert quality["status"] in {RENDER_QUALITY_PASS, RENDER_QUALITY_BLOCKED}
    if quality["status"] == RENDER_QUALITY_PASS:
        assert RENDER_TEXT_CLIPPED not in _codes(quality)


def test_person_identity_cases_f_to_j() -> None:
    assert classify_person_identity("Julia Harbor", "Julia Harbor") == PERSON_MATCH
    assert classify_person_identity("Julia Harbor, Realtor", "Julia Harbor") == PERSON_MATCH
    assert classify_person_identity("Harbor Realty", "Julia Harbor") == PERSON_NOT_REFERENCED
    assert classify_person_identity("Julia Smith", "Julia Harbor") == PERSON_MISMATCH
    assert classify_person_identity("Julian Harbor", "Julia Harbor") == PERSON_MISMATCH
    assert _copy_result("Julia Smith").status == QUALITY_BLOCKED
    assert PERSON_NAME_MISMATCH in {r.code for r in _copy_result("Julian Harbor").reasons}
    assert _copy_result("Harbor Realty").status == QUALITY_PASS


def test_case_k_seo_title_not_blindly_reused() -> None:
    data = {
        "url": "https://harbor.example/julia-harbor",
        "company": "Harbor Realty",
        "headline": "Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty",
        "ad_copy": "Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty",
        "html": "<html><head><title>Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty</title></head><body><h1>Julia Harbor</h1></body></html>",
        "metadata": {"title": "Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty"},
        "person_context": {"contact_name": "Julia Harbor", "contact_title": "Realtor", "resolved_profile_url": "https://harbor.example/julia-harbor"},
        "business_intel": {"categories": ["realtor"]},
    }
    ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(data), template="realtor")
    assert ctx.headline == "Work With Julia"
    assert "|" not in ctx.headline
    assert ctx.headline != data["headline"]


def test_7d_person_mismatch_equivalent_remediated_safely() -> None:
    result = _copy_result("Work With Julia", contact_name="Julia Harbor", company="Harbor Realty Partners")
    assert result.status == QUALITY_PASS


def test_render_diagnostics_survive_json_serialization(tmp_path) -> None:
    quality = _render(tmp_path, headline="Commercial real estate and leasing in Portland.", template="realtor")
    restored = json.loads(json.dumps(quality))
    assert restored["diagnostics"]["headline_font_size_used"] == quality["diagnostics"]["headline_font_size_used"]
