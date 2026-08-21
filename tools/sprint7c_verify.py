from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.mockup_result import MockupResult  # noqa: E402
from gui.models.prospect import Prospect  # noqa: E402
from gui.models.prospect_generation_store import ProspectGenerationStore  # noqa: E402
from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.models.project_store import ProjectStore  # noqa: E402
from gui.services.campaign_export import CampaignExportService  # noqa: E402
from gui.services.email_enrichment import (  # noqa: E402
    EMAIL_ORIGIN_ENRICHED,
    STATUS_BLOCKED_CONTENT,
    STATUS_FOUND,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED_EXISTING,
    TYPE_INFO,
    TYPE_PERSON,
    enrich_and_persist_prospect_email,
    enrich_prospect_email,
)
from gui.services.prospect_generation import ProspectGenerationService  # noqa: E402


def check(label: str, condition: bool, failures: list[str]) -> None:
    if condition:
        print(f"PASS {label}")
    else:
        print(f"FAIL {label}")
        failures.append(label)


def prospect(**overrides) -> Prospect:
    base = dict(
        prospect_id="p1",
        company_name="ABC Roofing LLC",
        company_name_for_ads="ABC Roofing",
        website="https://abcroofing.com",
        domain="abcroofing.com",
        category="roofing",
        contact_name="Jane Smith",
        metadata={"field_provenance": {"email": {"origin": "IMPORTED", "source_column": "Email"}}},
    )
    base.update(overrides)
    return Prospect(**base)


def main() -> int:
    failures: list[str] = []

    calls: list[str] = []
    existing = prospect(email="owner@roofingco.com")
    existing_result = enrich_prospect_email(existing, fetcher=lambda url: calls.append(url) or "info@abcroofing.com")
    check("1 existing email skips enrichment", existing_result.status == STATUS_SKIPPED_EXISTING and existing_result.attempted is False, failures)
    enrich_and_persist_prospect_email(existing, fetcher=lambda url: "info@abcroofing.com")
    check("2 existing email preserved", existing.email == "owner@roofingco.com" and existing.metadata["field_provenance"]["email"]["origin"] == "IMPORTED", failures)
    check("18 no network side effects beyond supplied/local fake fetcher", calls == [], failures)

    mailto = prospect(email="", metadata={})
    mailto_result = enrich_and_persist_prospect_email(mailto, scrape_data={"url": mailto.website, "html": '<a href="mailto:Info@ABCRoofing.com?subject=x">Email</a>'})
    check("3 missing email triggers enrichment", mailto_result.attempted is True, failures)
    check("4 mailto extraction", mailto.email == "info@abcroofing.com", failures)
    check("12 provenance stored", mailto.metadata["field_provenance"]["email"]["origin"] == EMAIL_ORIGIN_ENRICHED, failures)

    text = prospect(email="", metadata={})
    text_result = enrich_and_persist_prospect_email(text, scrape_data={"url": text.website, "html": "Write sales@abcroofing.com"})
    check("5 text extraction", text_result.status == STATUS_FOUND and text.email == "sales@abcroofing.com", failures)

    malformed = prospect(email="", metadata={})
    malformed_result = enrich_and_persist_prospect_email(malformed, scrape_data={"url": malformed.website, "html": "Bad user@@abcroofing.com and example@example.com"})
    check("6 malformed email rejection", malformed.email == "" and malformed_result.status == STATUS_NOT_FOUND, failures)

    challenge = prospect(email="", metadata={})
    challenge_result = enrich_and_persist_prospect_email(challenge, scrape_data={"url": challenge.website, "html": "Please verify you are human captcha info@abcroofing.com"})
    check("7 challenge content rejection", challenge_result.status == STATUS_BLOCKED_CONTENT and challenge.email == "", failures)

    unrelated = prospect(email="", metadata={})
    unrelated_result = enrich_and_persist_prospect_email(unrelated, scrape_data={"url": unrelated.website, "html": "employee@othercompany.com"})
    check("8 unrelated-domain rejection", unrelated.email == "" and "unrelated_third_party_domain" in unrelated_result.diagnostics["email_candidate_rejection_reasons"], failures)

    free = prospect(email="", metadata={})
    free_result = enrich_and_persist_prospect_email(free, scrape_data={"url": free.website, "html": "ABC Roofing: abcroofing@gmail.com"})
    check("9 free-mail contextual acceptance", free_result.status == STATUS_FOUND and free.email == "abcroofing@gmail.com", failures)

    multi = prospect(email="", metadata={}, resolved_profile_url="https://abcroofing.com/team/jane", resolution_status="RESOLVED")
    multi_result = enrich_and_persist_prospect_email(multi, scrape_data={"url": multi.resolved_profile_url, "html": "info@abcroofing.com sales@abcroofing.com Jane Smith jane.smith@abcroofing.com"})
    check("10 deterministic candidate ranking", multi.email == "jane.smith@abcroofing.com" and multi_result.selected and multi_result.selected.email_type == TYPE_PERSON, failures)
    check("11 alternatives preserved", [a["email"] for a in multi.metadata["email_enrichment"]["email_alternatives"]] == ["sales@abcroofing.com", "info@abcroofing.com"], failures)

    with tempfile.TemporaryDirectory() as tmp:
        store = ProspectStore(path=os.path.join(tmp, "prospects.json"))
        store.create(mailto)
        store.save()
        loaded = ProspectStore(path=store.path)
        loaded.load()
        reloaded = loaded.get(mailto.prospect_id)
        check("13 serialization/reload", reloaded is not None and reloaded.email == "info@abcroofing.com" and reloaded.metadata["email_enrichment"]["selected_email"] == "info@abcroofing.com", failures)

        blank = prospect(prospect_id="blank", email="", metadata={})
        blank_result = enrich_and_persist_prospect_email(blank, scrape_data={"url": blank.website, "html": "No email"})
        check("14 NOT_FOUND leaves blank email", blank_result.status == STATUS_NOT_FOUND and blank.email == "", failures)

        generation_store = ProspectStore(path=os.path.join(tmp, "gen_prospects.json"))
        generation_store.create(blank)
        jobs = ProspectGenerationStore(path=os.path.join(tmp, "jobs.json"))
        projects = ProjectStore(root=os.path.join(tmp, "projects"))

        def fake_generate(request):
            return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path, company_name="ABC Roofing", extra={"scrape_data": {"url": blank.website, "html": "No email"}})

        service = ProspectGenerationService(prospect_store=generation_store, job_store=jobs, project_store=projects, generation_callable=fake_generate, default_output_root=tmp)
        created = service.create_job(blank.prospect_id)
        ran = service.run_job(created.job.id) if created.job else None
        check("15 no generation blocking from missing email", ran is not None and ran.status == "SUCCEEDED" and generation_store.get(blank.prospect_id).email == "", failures)

        unresolved = prospect(prospect_id="unresolved", email="", metadata={}, resolution_status="NOT_FOUND", resolved_profile_url="")
        unresolved_result = enrich_and_persist_prospect_email(unresolved, scrape_data={"url": unresolved.website, "html": "Office info@abcroofing.com"})
        check("16 unresolved person does not get false person email", unresolved.email == "info@abcroofing.com" and unresolved_result.selected and unresolved_result.selected.email_type == TYPE_INFO, failures)

        export_store = ProspectStore(path=os.path.join(tmp, "export_prospects.json"))
        export_store.create(unresolved)
        export = CampaignExportService(prospect_store=export_store, job_store=jobs, project_store=projects)
        check("17 Smartlead-compatible canonical email behavior", export.check_eligibility(unresolved.prospect_id).reasons != ("Missing email.",), failures)

    total = 18
    failed = len(failures)
    passed = total - failed
    print(f"Sprint 7C verifier: PASS {passed}/{total} FAIL {failed}/{total}")
    if failed:
        print("Failures:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())