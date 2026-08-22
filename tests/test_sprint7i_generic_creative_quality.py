from __future__ import annotations

import re

from engine.brand_profile import BrandProfileBuilder
from engine.renderer.renderer import RENDER_CTA_OVERFLOW, RENDER_QUALITY_BLOCKED, RENDER_TEXT_CLIPPED, get_last_render_quality, render_billboard
from gui.models.prospect import Prospect
from gui.models.render_context import RenderContext
from gui.services.canonical_prospect_intelligence import canonical_context, merge_canonical_with_scrape
from gui.services.generic_creative_strategy import (
    CALL,
    FOOD_RETAIL,
    HOME_SERVICE,
    PRODUCT_FORWARD,
    SERVICE_FORWARD,
    TYPOGRAPHY_FIRST,
    derive_generic_creative_strategy,
)
from gui.services.prospect_generation import GENERIC_TEMPLATE, ProspectGenerationService
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.project_store import ProjectStore


UNSUPPORTED = re.compile(r"#\s*1|\bbest\b|\bguaranteed\b|\bfree estimate\b|\blicensed\b|\binsured\b|award[ -]?winning|years? of experience|\bdiscount\b|\bsale\b", re.I)


def _prospect(**overrides) -> Prospect:
    base = dict(
        prospect_id="p1",
        company_name="Generic Business LLC",
        company_name_for_ads="Generic Business",
        website="https://generic.example",
        company_phone="6125550100",
        city="Aurora",
        state="CO",
        metadata={},
    )
    base.update(overrides)
    return Prospect(**base)


def _strategy(p: Prospect):
    return derive_generic_creative_strategy(canonical_context(p), website=p.website)


def test_vertical_specificity_without_industry_templates() -> None:
    landscaping = _strategy(_prospect(company_name_for_ads="Urban Green Landscapes", naics_codes=["561730"]))
    solar = _strategy(_prospect(company_name_for_ads="Odd Header Solar", company_keywords=["solar installation", "solar energy"]))
    bakery = _strategy(_prospect(company_name_for_ads="Neighborhood Cakes", company_keywords=["bakery", "custom cakes"]))
    moving = _strategy(_prospect(company_name_for_ads="North Loop Movers", company_keywords=["moving", "packing", "relocation"]))

    assert landscaping.creative_intent == HOME_SERVICE
    assert "landscap" in (landscaping.headline + landscaping.primary_service).lower()
    assert "solar" in (solar.headline + solar.primary_service).lower()
    assert bakery.creative_intent == FOOD_RETAIL
    assert re.search(r"bakery|cakes?", bakery.headline + " " + bakery.primary_service, flags=re.I)
    assert "moving" in (moving.headline + moving.primary_service).lower()
    assert len({landscaping.headline, solar.headline, bakery.headline, moving.headline}) == 4


def test_classification_precedence_and_diagnostics() -> None:
    p = _prospect(naics_codes=["561730"], company_keywords=["solar installation"], industry="Bakery")
    s = _strategy(p)
    assert s.classification_basis == "naics_codes"
    assert s.primary_service == "Landscaping Services"
    assert s.diagnostics["source_independent"] is True
    assert s.diagnostics["classification_basis"] == "naics_codes"


def test_visual_family_cta_location_and_brand_fallback() -> None:
    p = _prospect(company_name_for_ads="Neighborhood Cakes", company_keywords=["bakery", "custom cakes"], company_phone="3035551111")
    s = _strategy(p)
    assert s.visual_family == PRODUCT_FORWARD
    assert s.cta_theme == CALL
    assert s.cta == "Call 3035551111"
    assert s.location == "Aurora"
    assert s.brand_fallback_mode == TYPOGRAPHY_FIRST
    assert not UNSUPPORTED.search(" ".join([s.headline, s.subtitle, s.cta]))


def test_minimal_eligible_generic_is_restrained() -> None:
    p = _prospect(company_name_for_ads="Plain Local Co", company_keywords=["local services"], company_phone="", website="")
    s = _strategy(p)
    assert s.headline
    assert s.cta in {"Get Started", "Request Info", "Learn More"}
    assert not UNSUPPORTED.search(s.headline + " " + s.cta)


def test_challenge_content_excluded_but_safe_strategy_remains() -> None:
    p = _prospect(company_name_for_ads="Odd Header Solar", company_keywords=["solar installation"])
    merged = merge_canonical_with_scrape(
        {"company": "Please Verify You Are Human", "headline": "CAPTCHA", "ad_copy": "Checking your browser", "metadata": {"title": "Access denied"}},
        canonical_context(p),
    )
    ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(merged), template=GENERIC_TEMPLATE)
    assert "captcha" not in ctx.headline.lower()
    assert "verify" not in ctx.company_name.lower()
    assert "solar" in ctx.headline.lower() or "solar" in ctx.business_classification.lower()
    assert ctx.opportunity_context["generic_creative_strategy"]["creative_intent"] == HOME_SERVICE


def test_generic_render_preserves_quality_minimums(tmp_path) -> None:
    p = _prospect(company_name_for_ads="Urban Green Landscapes", naics_codes=["561730"])
    ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(p))), template=GENERIC_TEMPLATE)
    render_billboard(ctx.to_render_spec(), str(tmp_path / "generic.png"))
    q = get_last_render_quality()
    assert q["diagnostics"]["headline_font_size_used"] >= 24
    assert q["diagnostics"]["cta_font_size_used"] >= 14
    assert RENDER_CTA_OVERFLOW not in {r.get("code") for r in q.get("reasons", [])}


def test_impossible_clipping_still_blocks(tmp_path) -> None:
    ctx = RenderContext(company_name="Impossible Headline Lab", headline="X" * 300, cta="Call Today", template=GENERIC_TEMPLATE)
    render_billboard(ctx.to_render_spec(), str(tmp_path / "impossible.png"))
    q = get_last_render_quality()
    assert q["status"] == RENDER_QUALITY_BLOCKED
    assert RENDER_TEXT_CLIPPED in {r.get("code") for r in q.get("reasons", [])}


def test_explicit_templates_still_win(tmp_path) -> None:
    store = ProspectStore(path=str(tmp_path / "prospects.json"))
    cases = [
        _prospect(prospect_id="c", category="roofing", company_keywords=["roofing"]),
        _prospect(prospect_id="d", category="dental", company_keywords=["dental"]),
        _prospect(prospect_id="r", category="real estate", company_keywords=["realtor"]),
    ]
    for p in cases:
        store.create(p)
    store.save()
    service = ProspectGenerationService(
        prospect_store=store,
        job_store=ProspectGenerationStore(path=str(tmp_path / "jobs.json")),
        project_store=ProjectStore(root=str(tmp_path / "projects")),
    )
    assert service.check_eligibility("c").resolved_template == "contractor"
    assert service.check_eligibility("d").resolved_template == "dentist"
    assert service.check_eligibility("r").resolved_template == "realtor"


def test_rich_generic_uses_stronger_keywords() -> None:
    p = _prospect(company_name_for_ads="North Loop Movers", company_keywords=["moving", "packing", "relocation"], industry="Logistics")
    s = _strategy(p)
    assert s.classification_basis == "company_keywords"
    assert "moving" in s.primary_service.lower() or "moving" in s.headline.lower()
    assert s.visual_family == SERVICE_FORWARD
