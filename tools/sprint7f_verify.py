"""Sprint 7F deterministic creative-quality verifier."""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from engine.content_safety import CHALLENGE_CONTENT_DETECTED  # noqa: E402
from engine.renderer.renderer import RENDER_CTA_OVERFLOW, RENDER_QUALITY_BLOCKED, RENDER_QUALITY_PASS, RENDER_TEXT_CLIPPED, get_last_render_quality, render_billboard  # noqa: E402
from gui.models.mockup_concept import MockupConcept  # noqa: E402
from gui.models.project import Project  # noqa: E402
from gui.models.prospect import Prospect  # noqa: E402
from gui.models.render_context import RenderContext  # noqa: E402
from gui.services.copy_quality import PERSON_MATCH, PERSON_MISMATCH, PERSON_NAME_MISMATCH, PERSON_NOT_REFERENCED, QUALITY_BLOCKED, QUALITY_PASS, assess_copy_quality, classify_person_identity  # noqa: E402


class Row:
    def __init__(self, headline: str, cta: str = "Call Today", body: str = "") -> None:
        self.headline = headline
        self.cta = cta
        self.email_subject = ""
        self.email_body = body


def check(label: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {label}")
    counts["passed" if condition else "failed"] += 1


def render_case(tmp: str, name: str, headline: str, cta: str = "Call Today", template: str = "contractor", opportunity_context: dict | None = None) -> tuple[dict, str]:
    path = os.path.join(tmp, f"{name}.png")
    spec = RenderContext(company_name="Example Co", headline=headline, cta=cta, template=template, opportunity_context=opportunity_context or {}).to_render_spec()
    render_billboard(spec, path)
    return get_last_render_quality(), path


def codes(quality: dict) -> set[str]:
    return {str(r.get("code")) for r in quality.get("reasons") or []}


def copy_result(headline: str, contact_name: str = "Julia Harbor", company: str = "Harbor Realty"):
    prospect = Prospect(prospect_id="p1", company_name=company, website="https://example.test", email="a@example.test", contact_name=contact_name)
    concept = MockupConcept.create("mock.png", "realtor", headline, "Let's Talk", 90, company_name=company)
    return assess_copy_quality(prospect=prospect, concept=concept, project=Project(company=company), row=Row(headline, cta="Let's Talk"))


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    sample_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sprint7f_verify_") as tmp:
        normal, path = render_case(tmp, "normal", "Trusted Local Roofing")
        sample_paths.append(path)
        check("1 normal headline fit unchanged", normal.get("status") == RENDER_QUALITY_PASS and normal.get("diagnostics", {}).get("headline_fit_adjusted") is False, counts)

        adjusted, path = render_case(tmp, "adjusted", "Commercial real estate and leasing in Portland.", template="realtor")
        sample_paths.append(path)
        check("2 bounded headline font adjustment", adjusted.get("status") == RENDER_QUALITY_PASS and adjusted.get("diagnostics", {}).get("headline_font_size_used", 0) >= 24, counts)
        check("3 bounded wrapping", adjusted.get("diagnostics", {}).get("headline_wrapped_lines", 0) > 1, counts)

        tiny, _ = render_case(tmp, "tiny_block", "Unbreakable" * 40)
        check("4 minimum font prevents unreadable shrinking", tiny.get("diagnostics", {}).get("headline_font_size_used", 0) >= 24 and tiny.get("status") == RENDER_QUALITY_BLOCKED, counts)

        impossible, _ = render_case(tmp, "impossible", "X" * 300)
        check("5 impossible headline still blocks", impossible.get("status") == RENDER_QUALITY_BLOCKED, counts)

        cta, _ = render_case(tmp, "cta", "Dental Care In Aurora", cta="Schedule Your Visit")
        check("6 CTA fit adjustment", RENDER_CTA_OVERFLOW not in codes(cta) and cta.get("diagnostics", {}).get("cta_font_size_used", 0) >= 14, counts)

        check("7 exact person match", classify_person_identity("Julia Harbor", "Julia Harbor") == PERSON_MATCH, counts)
        check("8 person + title match", classify_person_identity("Julia Harbor, Realtor", "Julia Harbor") == PERSON_MATCH, counts)
        check("9 company-only no false mismatch", classify_person_identity("Harbor Realty", "Julia Harbor") == PERSON_NOT_REFERENCED and copy_result("Harbor Realty").status == QUALITY_PASS, counts)
        check("10 wrong person blocked", copy_result("Julia Smith").status == QUALITY_BLOCKED, counts)
        check("11 similar wrong person blocked", PERSON_NAME_MISMATCH in {r.code for r in copy_result("Julian Harbor").reasons}, counts)

        seo_data = {
            "url": "https://harbor.example/julia-harbor",
            "company": "Harbor Realty",
            "headline": "Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty",
            "ad_copy": "Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty",
            "html": "<html><head><title>Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty</title></head><body><h1>Julia Harbor</h1></body></html>",
            "metadata": {"title": "Julia Harbor, Harbor Realty Real Estate Agent | Harbor Realty"},
            "person_context": {"contact_name": "Julia Harbor", "contact_title": "Realtor", "resolved_profile_url": "https://harbor.example/julia-harbor"},
            "business_intel": {"categories": ["realtor"]},
        }
        seo_ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(seo_data), template="realtor")
        check("12 SEO title not blindly reused", seo_ctx.headline == "Work With Julia" and "|" not in seo_ctx.headline, counts)

        generic_ctx = {"canonical_prospect_intelligence": {"classification": {"label": "Professional Residential Landscaping Services", "keywords": ["Residential Landscaping"]}}}
        generic, path = render_case(tmp, "generic_long", "Professional Residential Landscaping Services With Seasonal Maintenance Planning", template="generic", opportunity_context=generic_ctx)
        sample_paths.append(path)
        check("13 generic template long classification safely handled", generic.get("diagnostics", {}).get("headline_font_size_used", 0) >= 24 and (generic.get("status") == RENDER_QUALITY_BLOCKED or RENDER_TEXT_CLIPPED not in codes(generic)), counts)

        dental, _ = render_case(tmp, "dental_7d", "Cosmetic and family dentistry in Aurora. Email smiles@clearwaterdentalco.com", cta="Call 7205552200", template="dentist")
        check("14 7D dental clipping equivalent remediated", dental.get("status") == RENDER_QUALITY_PASS and RENDER_TEXT_CLIPPED not in codes(dental), counts)
        realtor, _ = render_case(tmp, "realtor_7d", "Commercial real estate and leasing in Portland.", cta="Call 5035559900", template="realtor")
        check("15 7D realtor clipping equivalent remediated", realtor.get("status") == RENDER_QUALITY_PASS and RENDER_TEXT_CLIPPED not in codes(realtor), counts)
        check("16 7D person mismatch equivalent remediated safely", copy_result("Work With Julia", company="Harbor Realty Partners").status == QUALITY_PASS, counts)

        challenge = copy_result("Please Verify You Are Human")
        check("17 existing quality gates remain active", challenge.status == QUALITY_BLOCKED and CHALLENGE_CONTENT_DETECTED in {r.code for r in challenge.reasons}, counts)
        check("18 diagnostics survive serialization", json.loads(json.dumps(adjusted))["diagnostics"]["headline_font_size_used"] == adjusted["diagnostics"]["headline_font_size_used"], counts)

        print("Rendered sample paths:")
        for path in sample_paths:
            print(f" - {path}")

    total = counts["passed"] + counts["failed"]
    print(f"Sprint 7F verifier: PASS {counts['passed']}/{total} FAIL {counts['failed']}/{total}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
