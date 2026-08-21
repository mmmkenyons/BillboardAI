from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from gui.models.mockup_result import MockupResult  # noqa: E402
from gui.models.prospect import Prospect  # noqa: E402
from gui.models.prospect_generation_store import ProspectGenerationStore  # noqa: E402
from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.models.project_store import ProjectStore  # noqa: E402
from gui.models.render_context import RenderContext  # noqa: E402
from gui.services.canonical_prospect_intelligence import canonical_context, merge_canonical_with_scrape, select_creative_phone  # noqa: E402
from gui.services.prospect_generation import GENERIC_TEMPLATE, ProspectGenerationService  # noqa: E402


def check(label: str, condition: bool, failures: list[str]) -> None:
    print(("PASS" if condition else "FAIL") + f" {label}")
    if not condition:
        failures.append(label)


def prospect(**overrides) -> Prospect:
    base = dict(
        prospect_id="p1",
        company_name="Generic Co LLC",
        company_name_for_ads="Generic Co",
        website="https://generic.example",
        company_phone="6125550100",
        mobile_phone="6125550111",
        city="Minneapolis",
        state="MN",
        metadata={},
    )
    base.update(overrides)
    return Prospect(**base)


def make_service(tmp: str, p: Prospect, fake_generate=None) -> ProspectGenerationService:
    store = ProspectStore(path=os.path.join(tmp, f"prospects_{p.prospect_id}.json"))
    store.create(p)
    store.save()
    return ProspectGenerationService(
        prospect_store=store,
        job_store=ProspectGenerationStore(path=os.path.join(tmp, f"jobs_{p.prospect_id}.json")),
        project_store=ProjectStore(root=os.path.join(tmp, f"projects_{p.prospect_id}")),
        generation_callable=fake_generate,
        default_output_root=tmp,
    )


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        explicit = [("roof", "roofing", "contractor"), ("dent", "dental", "dentist"), ("real", "real estate", "realtor")]
        for pid, category, expected in explicit:
            svc = make_service(tmp, prospect(prospect_id=pid, category=category, company_keywords=[category]))
            created = svc.create_job(pid)
            check(f"explicit template preserved {expected}", created.job is not None and created.job.template == expected and created.job.metadata["template_selection"]["generic_fallback_used"] is False, failures)

        generic_cases = [
            ("land", prospect(prospect_id="land", company_name_for_ads="Urban Green Landscapes", naics_codes=["561730"])),
            ("solar", prospect(prospect_id="solar", company_name_for_ads="Odd Header Solar", company_keywords=["solar installation"])),
            ("bakery", prospect(prospect_id="bakery", company_name_for_ads="Neighborhood Cakes", naics_codes=["311811"])),
            ("moving", prospect(prospect_id="moving", company_name_for_ads="North Loop Movers", company_keywords=["moving", "logistics"])),
        ]
        for pid, p in generic_cases:
            svc = make_service(tmp, p)
            created = svc.create_job(pid)
            check(f"generic fallback eligible {pid}", created.job is not None and created.job.template == GENERIC_TEMPLATE and created.job.metadata["template_selection"]["generic_fallback_reason"] == "GENERIC_FALLBACK_ELIGIBLE", failures)

        minimal = prospect(prospect_id="minimal", website="", category="", naics_codes=[], company_keywords=[], industry="", company_phone="", mobile_phone="")
        min_svc = make_service(tmp, minimal)
        min_el = min_svc.check_eligibility("minimal")
        check("minimal insufficient-intelligence rejection", not min_el.eligible and "GENERIC_FALLBACK_INSUFFICIENT_INTELLIGENCE" in min_el.reasons, failures)

        seen: dict[str, str] = {}
        def fake_generate(request):
            seen["url"] = request.url
            seen["template"] = request.template
            return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)
        blank_site = prospect(prospect_id="blanksite", website="", domain="", company_keywords=["bakery"])
        blank_svc = make_service(tmp, blank_site, fake_generate=fake_generate)
        blank_created = blank_svc.create_job("blanksite")
        blank_ran = blank_svc.run_job(blank_created.job.id) if blank_created.job else None
        check("blank website generic generation", blank_ran is not None and blank_ran.status == "SUCCEEDED" and seen == {"url": "", "template": GENERIC_TEMPLATE}, failures)

        challenge_p = prospect(company_name_for_ads="Odd Header Solar", company_keywords=["solar installation"])
        merged = merge_canonical_with_scrape({"company": "Please Verify You Are Human", "headline": "CAPTCHA", "ad_copy": "Checking your browser", "metadata": {"title": "Access denied"}}, canonical_context(challenge_p))
        profile = BrandProfileBuilder.from_scrape_data(merged)
        ctx = RenderContext.from_brand_profile(profile, template=GENERIC_TEMPLATE)
        check("challenge content safety preserved", profile.company_name == "Odd Header Solar" and "CAPTCHA" not in ctx.headline and ctx.opportunity_context["generic_fallback_policy"]["code"] == "GENERIC_FALLBACK_ELIGIBLE", failures)

        legal = prospect(company_name="T2 Roofing LLC", company_name_for_ads="T2 Roofing", company_keywords=["landscaping"], resolution_status="NOT_FOUND", contact_name="Jane Smith", email="existing@example.com", company_phone="3035550199", mobile_phone="3035550101")
        legal_ctx = RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(legal))), template=GENERIC_TEMPLATE)
        check("display company preferred over legal", legal_ctx.company_name == "T2 Roofing", failures)
        check("unresolved person no substitution", legal_ctx.opportunity_context["person_facts"]["contact_name"] == "", failures)
        check("existing email preserved", legal.email == "existing@example.com", failures)
        blank_email = prospect(prospect_id="blankemail", email="", company_keywords=["bakery"])
        check("blank email does not prevent generation", make_service(tmp, blank_email).check_eligibility("blankemail").eligible, failures)
        check("canonical phone selection preserved", select_creative_phone(legal)["phone"] == "3035550199", failures)
        check("provenance identifies generic fallback", legal_ctx.opportunity_context["generic_fallback_used"] is True and legal_ctx.opportunity_context["business_classification_source"] == "company_keywords", failures)

    total = 16
    print(f"Sprint 7E verifier: PASS {total - len(failures)}/{total} FAIL {len(failures)}/{total}")
    if failures:
        for failure in failures:
            print(f" - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())