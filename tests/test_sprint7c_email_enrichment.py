from __future__ import annotations

import os

from gui.models.mockup_result import MockupResult
from gui.models.prospect import Prospect
from gui.models.prospect_generation import ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.project_store import ProjectStore
from gui.services.campaign_export import CampaignExportService, EXPORT_STATUS_BLOCKED
from gui.services.email_enrichment import (
    EMAIL_ORIGIN_ENRICHED,
    REASON_EXISTING_EMAIL_PRESENT,
    STATUS_BLOCKED_CONTENT,
    STATUS_FOUND,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED_EXISTING,
    TYPE_INFO,
    TYPE_PERSON,
    enrich_and_persist_prospect_email,
    enrich_prospect_email,
)
from gui.services.prospect_generation import ProspectGenerationService


def _prospect(**overrides) -> Prospect:
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


def test_existing_imported_email_skips_enrichment_and_preserves_provenance() -> None:
    calls = []
    p = _prospect(email="Owner@RoofingCo.com")
    result = enrich_prospect_email(p, fetcher=lambda url: calls.append(url) or "info@abcroofing.com")
    assert result.status == STATUS_SKIPPED_EXISTING
    assert result.attempted is False
    assert result.reason == REASON_EXISTING_EMAIL_PRESENT
    assert calls == []
    enrich_and_persist_prospect_email(p, fetcher=lambda url: "info@abcroofing.com")
    assert p.email == "Owner@RoofingCo.com"
    assert p.metadata["field_provenance"]["email"]["origin"] == "IMPORTED"
    assert p.metadata["email_enrichment"]["email_enrichment_attempted"] is False


def test_blank_email_mailto_is_normalized_persisted_with_provenance() -> None:
    p = _prospect(email="")
    html = '<a href="mailto:Info@ABCRoofing.com?subject=Hi">Email us</a>'
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": html})
    assert result.status == STATUS_FOUND
    assert p.email == "info@abcroofing.com"
    assert p.metadata["field_provenance"]["email"]["origin"] == EMAIL_ORIGIN_ENRICHED
    assert p.metadata["email_enrichment"]["selected_email_source_url"] == p.website


def test_plain_text_email_safe_discovery() -> None:
    p = _prospect(email="")
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "Contact ABC Roofing at Sales@ABCRoofing.com today."})
    assert result.status == STATUS_FOUND
    assert p.email == "sales@abcroofing.com"


def test_multiple_emails_rank_person_specific_and_preserve_alternatives() -> None:
    p = _prospect(email="", resolved_profile_url="https://abcroofing.com/team/jane", resolution_status="RESOLVED")
    html = "Reach info@abcroofing.com or sales@abcroofing.com. Jane Smith: jane.smith@abcroofing.com"
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.resolved_profile_url, "html": html})
    assert p.email == "jane.smith@abcroofing.com"
    assert result.selected is not None and result.selected.email_type == TYPE_PERSON
    alternatives = p.metadata["email_enrichment"]["email_alternatives"]
    assert [a["email"] for a in alternatives] == ["sales@abcroofing.com", "info@abcroofing.com"]


def test_unrelated_third_party_email_rejected() -> None:
    p = _prospect(email="")
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "Bad contamination employee@othercompany.com"})
    assert result.status == STATUS_NOT_FOUND
    assert p.email == ""
    assert "unrelated_third_party_domain" in p.metadata["email_enrichment"]["email_candidate_rejection_reasons"]


def test_challenge_page_blocks_extraction_without_crashing() -> None:
    p = _prospect(email="")
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "Please verify you are human contact info@abcroofing.com captcha"})
    assert result.status == STATUS_BLOCKED_CONTENT
    assert p.email == ""


def test_no_email_found_leaves_blank_not_found() -> None:
    p = _prospect(email="")
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "ABC Roofing home page"})
    assert result.status == STATUS_NOT_FOUND
    assert p.email == ""


def test_free_mail_address_contextually_accepted() -> None:
    p = _prospect(email="")
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "ABC Roofing email: abcroofing@gmail.com"})
    assert result.status == STATUS_FOUND
    assert p.email == "abcroofing@gmail.com"


def test_unresolved_person_generic_company_email_not_claimed_as_person() -> None:
    p = _prospect(email="", contact_name="Jane Smith", resolved_profile_url="", resolution_status="NOT_FOUND")
    result = enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "Office: info@abcroofing.com"})
    assert p.email == "info@abcroofing.com"
    assert result.selected is not None
    assert result.selected.email_type == TYPE_INFO
    assert result.selected.association == "COMPANY"


def test_contact_page_fetch_is_bounded_and_same_domain() -> None:
    p = _prospect(email="")
    calls = []
    pages = {
        "https://abcroofing.com": '<a href="https://abcroofing.com/contact">Contact</a><a href="https://other.com/contact">Other</a>',
        "https://abcroofing.com/contact": "Email contact@abcroofing.com",
    }

    def fetch(url):
        calls.append(url)
        return pages[url]

    result = enrich_and_persist_prospect_email(p, fetcher=fetch, max_pages=2)
    assert result.status == STATUS_FOUND
    assert p.email == "contact@abcroofing.com"
    assert calls == ["https://abcroofing.com", "https://abcroofing.com/contact"]


def test_generation_missing_email_failure_does_not_block_mockup(tmp_path, monkeypatch) -> None:
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    p = _prospect(email="")
    store.create(p)
    jobs = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    projects = ProjectStore(root=os.path.join(str(tmp_path), "projects"))

    def fake_generate(request):
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path, company_name="ABC Roofing", extra={"scrape_data": {"url": p.website, "html": "No email here"}})

    monkeypatch.setattr("gui.services.prospect_generation.enrich_and_persist_prospect_email", lambda prospect, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    service = ProspectGenerationService(prospect_store=store, job_store=jobs, project_store=projects, generation_callable=fake_generate, default_output_root=str(tmp_path))
    created = service.create_job(p.prospect_id)
    assert created.job is not None
    job = service.run_job(created.job.id)
    assert job.status == "SUCCEEDED"
    assert store.get(p.prospect_id).email == ""


def test_smartlead_compatible_campaign_export_uses_enriched_email(tmp_path) -> None:
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    p = _prospect(email="")
    enrich_and_persist_prospect_email(p, scrape_data={"url": p.website, "html": "Email sales@abcroofing.com"})
    store.create(p)
    jobs = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    projects = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    project = projects.create(company_name=p.company_name, website=p.website)
    project.image_path = str(tmp_path)
    projects.save(project)
    job = ProspectGenerationJob(prospect_id=p.prospect_id, website=p.website, template="contractor", status="SUCCEEDED", project_id=project.id, result_path=os.path.join(str(tmp_path), "mock.png"))
    jobs.upsert(job)
    jobs.save()
    # No concept means still blocked for mockup resolution, but missing email is no longer the blocker.
    export = CampaignExportService(prospect_store=store, job_store=jobs, project_store=projects)
    assert export.check_eligibility(p.prospect_id).reasons != ("Missing email.",)

    missing = _prospect(prospect_id="p2", email="")
    store.create(missing)
    assert export.check_eligibility("p2").status == EXPORT_STATUS_BLOCKED
    assert export.check_eligibility("p2").reasons == ("Missing email.",)