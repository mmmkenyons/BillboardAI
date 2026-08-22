"""Sprint 7I deterministic generic creative-quality verifier."""

from __future__ import annotations

import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from engine.renderer.renderer import RENDER_CTA_OVERFLOW, RENDER_QUALITY_BLOCKED, RENDER_TEXT_CLIPPED, get_last_render_quality, render_billboard  # noqa: E402
from gui.models.mockup_concept import MockupConcept  # noqa: E402
from gui.models.project import Project  # noqa: E402
from gui.models.prospect import Prospect  # noqa: E402
from gui.models.prospect_generation_store import ProspectGenerationStore  # noqa: E402
from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.models.project_store import ProjectStore  # noqa: E402
from gui.models.render_context import RenderContext  # noqa: E402
from gui.services.canonical_prospect_intelligence import canonical_context, merge_canonical_with_scrape, select_creative_phone  # noqa: E402
from gui.services.copy_quality import PERSON_NAME_MISMATCH, QUALITY_BLOCKED, assess_copy_quality  # noqa: E402
from gui.services.generic_creative_strategy import derive_generic_creative_strategy  # noqa: E402
from gui.services.prospect_generation import GENERIC_TEMPLATE, ProspectGenerationService  # noqa: E402


UNSUPPORTED = re.compile(r"#\s*1|\bbest\b|\bguaranteed\b|\bfree estimate\b|\blicensed\b|\binsured\b|award[ -]?winning|years? of experience|\bdiscount\b|\bsale\b", re.I)


class Row:
    def __init__(self, headline: str, cta: str = "Call Today") -> None:
        self.headline = headline
        self.cta = cta
        self.email_subject = ""
        self.email_body = ""


def check(label: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {label}")
    counts["passed" if condition else "failed"] += 1


def prospect(**overrides) -> Prospect:
    base = dict(
        prospect_id="p1",
        company_name="Generic Co LLC",
        company_name_for_ads="Generic Co",
        website="https://generic.example",
        company_phone="6125550100",
        city="Aurora",
        state="CO",
        metadata={},
    )
    base.update(overrides)
    return Prospect(**base)


def strategy(p: Prospect):
    return derive_generic_creative_strategy(canonical_context(p), website=p.website)


def render_ctx(tmp: str, name: str, ctx: RenderContext) -> dict:
    render_billboard(ctx.to_render_spec(), os.path.join(tmp, f"{name}.png"))
    return get_last_render_quality()


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    land = strategy(prospect(company_name_for_ads="Urban Green Landscapes", naics_codes=["561730"]))
    solar = strategy(prospect(company_name_for_ads="Odd Header Solar", company_keywords=["solar installation", "solar energy"]))
    bakery = strategy(prospect(company_name_for_ads="Neighborhood Cakes", company_keywords=["bakery", "custom cakes"]))
    moving = strategy(prospect(company_name_for_ads="North Loop Movers", company_keywords=["moving", "packing", "relocation"]))
    texts = [land.headline, solar.headline, bakery.headline, moving.headline]

    check("1 landscaping gets generic strategy", land.business_display_name == "Urban Green Landscapes" and land.creative_intent, counts)
    check("2 landscaping specificity", "landscap" in (land.headline + land.primary_service).lower(), counts)
    check("3 solar specificity", "solar" in (solar.headline + solar.primary_service).lower(), counts)
    check("4 bakery specificity", bool(re.search(r"bakery|cakes?", bakery.headline + " " + bakery.primary_service, flags=re.I)), counts)
    check("5 moving specificity", "moving" in (moving.headline + moving.primary_service).lower(), counts)
    check("6 categories do not collapse", len(set(texts)) == 4, counts)
    check("7 no unsupported claims", not any(UNSUPPORTED.search(" ".join([s.headline, s.subtitle, s.cta])) for s in (land, solar, bakery, moving)), counts)

    blank = prospect(company_name_for_ads="Blank Site Cakes", website="", company_keywords=["bakery", "custom cakes"])
    blank_ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(blank))), template=GENERIC_TEMPLATE)
    check("8 blank website works", blank_ctx.headline and blank_ctx.opportunity_context["brand_fallback_mode"] == "TYPOGRAPHY_FIRST", counts)

    challenge_p = prospect(company_name_for_ads="Odd Header Solar", company_keywords=["solar installation"])
    challenge_ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({"company": "Please Verify You Are Human", "headline": "CAPTCHA", "ad_copy": "Checking your browser", "metadata": {"title": "Access denied"}}, canonical_context(challenge_p))), template=GENERIC_TEMPLATE)
    check("9 challenge content excluded", "captcha" not in challenge_ctx.headline.lower() and "verify" not in challenge_ctx.company_name.lower(), counts)
    check("10 weak-brand fallback works", challenge_ctx.hero_image == "" and challenge_ctx.opportunity_context["brand_fallback_mode"] == "TYPOGRAPHY_FIRST", counts)

    phone_p = prospect(company_name_for_ads="Safe Phone Co", company_phone="3035550199", mobile_phone="1111111111", company_keywords=["local services"])
    check("11 safe phone preserved", select_creative_phone(phone_p)["phone"] == "3035550199" and strategy(phone_p).cta == "Call 3035550199", counts)
    check("12 display company preserved", RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(phone_p))), template=GENERIC_TEMPLATE).company_name == "Safe Phone Co", counts)

    with tempfile.TemporaryDirectory(prefix="sprint7i_verify_") as tmp:
        q = render_ctx(tmp, "generic", blank_ctx)
        check("13 generic render succeeds", os.path.exists(os.path.join(tmp, "generic.png")) and q.get("status") != RENDER_QUALITY_BLOCKED, counts)
        check("14 headline minimum preserved", q.get("diagnostics", {}).get("headline_font_size_used", 0) >= 24, counts)
        check("15 CTA minimum preserved", q.get("diagnostics", {}).get("cta_font_size_used", 0) >= 14 and RENDER_CTA_OVERFLOW not in {r.get("code") for r in q.get("reasons", [])}, counts)
        impossible = render_ctx(tmp, "impossible", RenderContext(company_name="Impossible", headline="X" * 300, cta="Call Today", template=GENERIC_TEMPLATE))
        check("16 impossible clipping still blocks", impossible.get("status") == RENDER_QUALITY_BLOCKED and RENDER_TEXT_CLIPPED in {r.get("code") for r in impossible.get("reasons", [])}, counts)

    concept = MockupConcept.create("mock.png", "realtor", "Julia Smith", "Let's Talk", 90, company_name="Harbor Realty")
    wrong = assess_copy_quality(prospect=Prospect(prospect_id="wp", company_name="Harbor Realty", website="https://example.test", email="a@example.test", contact_name="Julia Harbor"), concept=concept, project=Project(company="Harbor Realty"), row=Row("Julia Smith", "Let's Talk"))
    check("17 wrong person still blocks", wrong.status == QUALITY_BLOCKED and PERSON_NAME_MISMATCH in {r.code for r in wrong.reasons}, counts)
    check("18 source independence preserved", land.diagnostics.get("source_independent") is True, counts)
    check("19 diagnostics/provenance present", bool(land.to_dict().get("diagnostics", {}).get("classification_basis")) and land.classification_basis, counts)

    with tempfile.TemporaryDirectory(prefix="sprint7i_templates_") as tmp:
        store = ProspectStore(path=os.path.join(tmp, "prospects.json"))
        cases = [
            prospect(prospect_id="contractor", category="roofing", company_keywords=["roofing"]),
            prospect(prospect_id="dentist", category="dental", company_keywords=["dental"]),
            prospect(prospect_id="realtor", category="real estate", company_keywords=["realtor"]),
        ]
        for p in cases:
            store.create(p)
        store.save()
        service = ProspectGenerationService(prospect_store=store, job_store=ProspectGenerationStore(path=os.path.join(tmp, "jobs.json")), project_store=ProjectStore(root=os.path.join(tmp, "projects")))
        check("20 explicit contractor template still wins", service.check_eligibility("contractor").resolved_template == "contractor", counts)
        check("21 explicit dentist template still wins", service.check_eligibility("dentist").resolved_template == "dentist", counts)
        check("22 explicit realtor template still wins", service.check_eligibility("realtor").resolved_template == "realtor", counts)

    total = counts["passed"] + counts["failed"]
    print(f"Sprint 7I verifier: PASS {counts['passed']}/{total} FAIL {counts['failed']}/{total}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
