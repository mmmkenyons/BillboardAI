from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from gui.models.prospect import Prospect  # noqa: E402
from gui.models.prospect_generation_store import ProspectGenerationStore  # noqa: E402
from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.models.project_store import ProjectStore  # noqa: E402
from gui.models.render_context import RenderContext  # noqa: E402
from gui.services.canonical_prospect_intelligence import (  # noqa: E402
    business_classification,
    canonical_context,
    has_generation_intelligence,
    merge_canonical_with_scrape,
    preferred_display_company_name,
    select_creative_phone,
)
from gui.services.prospect_generation import ProspectGenerationService  # noqa: E402


def check(name: str, condition: bool, failures: list[str]) -> None:
    print(("PASS" if condition else "FAIL") + f" {name}")
    if not condition:
        failures.append(name)


def prospect(**overrides) -> Prospect:
    data = dict(
        prospect_id="p1",
        company_name="T2 Roofing LLC",
        company_name_for_ads="T2 Roofing",
        company_phone="3035550199",
        mobile_phone="3035550101",
        work_direct_phone="3035550202",
        city="Denver",
        state="CO",
        naics_codes=["238160"],
        company_keywords=["roof repair", "residential roofing", "storm damage"],
        industry="Construction",
        email="",
        metadata={
            "field_provenance": {
                "company_name_for_ads": {"origin": "IMPORTED", "source_column": "Company name for emails"},
                "company_phone": {"origin": "IMPORTED", "source_column": "Corporate phone"},
                "naics_codes": {"origin": "IMPORTED", "source_column": "NAICS codes"},
            },
            "email_state": {"status": "email_missing", "email_enrichment_eligible": True},
        },
    )
    data.update(overrides)
    return Prospect(**data)


def main() -> int:
    failures: list[str] = []
    p = prospect()
    ctx = canonical_context(p, website_phone="3035558888")
    check("1 ad/display company name wins", preferred_display_company_name(p) == "T2 Roofing", failures)
    check("2 legal name remains preserved", ctx["legal_company_name"] == "T2 Roofing LLC" and p.company_name == "T2 Roofing LLC", failures)
    phone = select_creative_phone(p, website_phone="3035558888")
    check("3 corporate/business phone wins over mobile", phone["phone"] == "3035550199" and phone["source_field"] == "company_phone", failures)
    check("4 phone provenance survives", phone["origin"] == "IMPORTED" and phone["source_column"] == "Corporate phone", failures)
    classification = business_classification(p)
    check("5 NAICS-specific evidence outranks broad industry", classification["basis"] == "naics_codes" and classification["label"] == "Roofing Contractors", failures)
    no_site = prospect(website="", domain="")
    check("6 no-website canonical prospect remains usable", has_generation_intelligence(no_site), failures)
    challenge = merge_canonical_with_scrape({"company": "Verify Human", "headline": "Checking your browser", "ad_copy": "captcha required", "metadata": {"title": "Verify"}}, canonical_context(p))
    profile = BrandProfileBuilder.from_scrape_data(challenge)
    check("7 challenge content cannot overwrite canonical evidence", profile.company_name == "T2 Roofing" and profile.headline == "" and profile.phone == "3035550199", failures)
    rc = RenderContext.from_brand_profile(profile)
    check("8 canonical fallback reaches BrandProfile/RenderContext", rc.company_name == "T2 Roofing" and rc.selected_phone == "3035550199" and rc.business_classification == "Roofing Contractors", failures)
    unresolved = prospect(contact_name="Jane Smith", contact_title="Owner", resolution_status="NOT_FOUND", resolved_profile_url="", manual_profile_url="")
    unresolved_profile = BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(unresolved)))
    check("9 unresolved person cannot gain scraped identity/assets", unresolved_profile.person_facts.contact_name == "" and unresolved_profile.personalized_headline == "", failures)
    check("10 blank email remains blank and enrichment-eligible", ctx["email"] == "" and ctx["email_state"]["email_enrichment_eligible"] is True, failures)
    minimal = prospect(company_name="Minimal Co", company_name_for_ads="", website="", domain="", company_phone="", mobile_phone="", work_direct_phone="", naics_codes=[], company_keywords=[], industry="", city="Omaha", state="NE", metadata={})
    check("11 minimal generic source remains safe", minimal.company_name == "Minimal Co" and has_generation_intelligence(minimal), failures)
    with tempfile.TemporaryDirectory() as tmp:
        store = ProspectStore(path=os.path.join(tmp, "prospects.json"))
        store.create(p); store.save()
        loaded = ProspectStore(path=store.path); loaded.load()
        p2 = loaded.get("p1")
        bp = BrandProfileBuilder.from_scrape_data(merge_canonical_with_scrape({}, canonical_context(p2)))
        rc2 = RenderContext.from_brand_profile(bp)
        check("12 serialization/reload preserves required canonical intelligence", p2.company_name_for_ads == "T2 Roofing" and rc2.selected_phone == "3035550199", failures)
        gen = ProspectGenerationService(prospect_store=loaded, job_store=ProspectGenerationStore(path=os.path.join(tmp, "jobs.json")), project_store=ProjectStore(root=os.path.join(tmp, "projects")))
        check("13 generation eligibility accepts canonical fallback", gen.check_eligibility("p1").eligible, failures)

    total = 13
    print(f"Sprint 7B verifier: PASS {total - len(failures)}/{total} FAIL {len(failures)}/{total}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())