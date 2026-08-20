from __future__ import annotations

import csv
import os

import pytest

from gui.models.campaign_assembly import ASSEMBLY_STATUS_BLOCKED, ASSEMBLY_STATUS_READY, ASSEMBLY_STATUS_WARNING, CampaignAssemblyStore
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.mockup_concept import MockupConcept
from gui.models.personalization_field_catalog import PersonalizationFieldMappingStore
from gui.models.project_store import ProjectStore
from gui.models.prospect import CONFIDENCE_HIGH, RESOLUTION_NOT_FOUND, RESOLUTION_RESOLVED, Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_assembly import CampaignAssemblyService
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.copy_quality import (
    COMPANY_NAME_MISMATCH,
    GENERIC_PLACEHOLDER_COPY,
    PERSON_NAME_MISMATCH,
    PERSON_PROFILE_UNRESOLVED,
    QUALITY_BLOCKED,
    QUALITY_PASS,
    QUALITY_WARNING,
    SEO_TITLE_LIKE,
    TRUNCATED_PHRASE,
    UNSUPPORTED_NUMERIC_CLAIM,
    UNSUPPORTED_SUPERLATIVE,
    assess_copy_quality,
    assess_profile_quality,
)
from gui.services.campaign_run import CampaignRunService
from gui.services.smartlead_run_export import SmartleadRunExportService
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


class _Row:
    def __init__(self, headline="Trusted Local Roofing", cta="Call Today", subject="Quick billboard idea", body="A billboard for ABC Roofing."):
        self.headline = headline
        self.cta = cta
        self.email_subject = subject
        self.email_body = body
        self.personalization_basis = ""
        self.creative_summary = ""


def _prospect(**kw):
    data = dict(prospect_id="p1", company_name="ABC Roofing", website="https://abc.example", email="a@example.com", contact_name="Alice Owner", city="Castle Rock", state="CO", category="roofing")
    data.update(kw)
    return Prospect(**data)


def _concept(headline="Trusted Local Roofing", cta="Call Today", extra=None):
    return MockupConcept.create("mock.png", "contractor", headline, cta, 90, company_name="ABC Roofing", **(extra or {}))


def _project(project_store, prospect, source_text=""):
    project = project_store.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
    if source_text:
        project.metadata["source_evidence"] = source_text
    return project


def _codes(result):
    return {r.code for r in result.reasons}


def test_copy_clean_person_specific_pass(tmp_path):
    prospect = _prospect(contact_name="Alice Owner")
    project = _project(ProjectStore(root=str(tmp_path)), prospect, "Alice Owner local roofing specialist")
    result = assess_copy_quality(prospect=prospect, concept=_concept(), project=project, row=_Row(body="Alice, a billboard for ABC Roofing could highlight local roofing."))
    assert result.status == QUALITY_PASS


def test_copy_clean_business_specific_pass(tmp_path):
    prospect = _prospect(contact_name="")
    project = _project(ProjectStore(root=str(tmp_path)), prospect, "ABC Roofing offers roof repair")
    result = assess_copy_quality(prospect=prospect, concept=_concept(), project=project, row=_Row(body="A billboard for ABC Roofing could highlight roof repair."))
    assert result.status == QUALITY_PASS


def test_copy_unsupported_fastest_blocked(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect, "roofing contractor")
    result = assess_copy_quality(prospect=prospect, concept=_concept("Fastest Roofing in Town"), project=project, row=_Row(headline="Fastest Roofing in Town"))
    assert result.status == QUALITY_BLOCKED
    assert UNSUPPORTED_SUPERLATIVE in _codes(result)


def test_copy_supported_source_superlative_not_falsely_blocked(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect, "Customers voted ABC Roofing Best of Castle Rock")
    result = assess_copy_quality(prospect=prospect, concept=_concept("Best of Castle Rock"), project=project, row=_Row(headline="Best of Castle Rock"))
    assert UNSUPPORTED_SUPERLATIVE not in _codes(result)


def test_copy_unsupported_numeric_claim_blocked(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect, "roofing contractor")
    result = assess_copy_quality(prospect=prospect, concept=_concept("90 Years of Roofing"), project=project, row=_Row(headline="90 Years of Roofing"))
    assert result.status == QUALITY_BLOCKED
    assert UNSUPPORTED_NUMERIC_CLAIM in _codes(result)


def test_copy_supported_numeric_experience_pass(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect, "ABC Roofing has 20 years experience")
    result = assess_copy_quality(prospect=prospect, concept=_concept("20 Years Experience"), project=project, row=_Row(headline="20 Years Experience"))
    assert result.status == QUALITY_PASS


def test_copy_seo_title_like_warning(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect)
    result = assess_copy_quality(prospect=prospect, concept=_concept("ABC Roofing | Roof Repair Near You"), project=project, row=_Row(headline="ABC Roofing | Roof Repair Near You"))
    assert result.status == QUALITY_WARNING
    assert SEO_TITLE_LIKE in _codes(result)


def test_copy_truncated_phrase_blocked(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect)
    result = assess_copy_quality(prospect=prospect, concept=_concept("Join Today and Get a Free"), project=project, row=_Row(headline="Join Today and Get a Free"))
    assert result.status == QUALITY_BLOCKED
    assert TRUNCATED_PHRASE in _codes(result)


def test_copy_work_with_what_warning_or_blocked(tmp_path):
    prospect = _prospect()
    project = _project(ProjectStore(root=str(tmp_path)), prospect)
    result = assess_copy_quality(prospect=prospect, concept=_concept("Work With What"), project=project, row=_Row(headline="Work With What"))
    assert result.status in {QUALITY_WARNING, QUALITY_BLOCKED}
    assert GENERIC_PLACEHOLDER_COPY in _codes(result) or TRUNCATED_PHRASE in _codes(result)


def test_copy_person_name_mismatch_blocked(tmp_path):
    prospect = _prospect(contact_name="Alice Owner")
    project = _project(ProjectStore(root=str(tmp_path)), prospect)
    result = assess_copy_quality(prospect=prospect, concept=_concept(), project=project, row=_Row(body="Bob Owner at ABC Roofing should advertise here."))
    assert result.status == QUALITY_BLOCKED
    assert PERSON_NAME_MISMATCH in _codes(result)


def test_copy_company_mismatch_blocked(tmp_path):
    prospect = _prospect(company_name="ABC Roofing")
    project = _project(ProjectStore(root=str(tmp_path)), prospect)
    result = assess_copy_quality(prospect=prospect, concept=_concept(), project=project, row=_Row(body="A billboard for XYZ Roofing could perform well."))
    assert result.status == QUALITY_BLOCKED
    assert COMPANY_NAME_MISMATCH in _codes(result)


def test_blank_optional_personalization_no_false_blocker(tmp_path):
    prospect = _prospect(contact_name="")
    project = _project(ProjectStore(root=str(tmp_path)), prospect)
    result = assess_copy_quality(prospect=prospect, concept=_concept(), project=project, row=_Row(body="A billboard for ABC Roofing could perform well."))
    assert result.status == QUALITY_PASS


def test_profile_unresolved_person_warns_and_resolved_does_not():
    unresolved = _prospect(resolution_status=RESOLUTION_NOT_FOUND)
    resolved = _prospect(resolution_status=RESOLUTION_RESOLVED, resolution_confidence=CONFIDENCE_HIGH, resolved_profile_url="https://abc.example/alice-owner")
    assert assess_profile_quality(unresolved).status == QUALITY_WARNING
    assert PERSON_PROFILE_UNRESOLVED in _codes(assess_profile_quality(unresolved))
    assert assess_profile_quality(resolved).status == QUALITY_PASS


def _runtime(tmp_path):
    root = str(tmp_path)
    prospect_store = ProspectStore(path=os.path.join(root, "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
    project_store = ProjectStore(root=os.path.join(root, "projects"))
    review_store = CampaignReviewStore(path=os.path.join(root, "campaign_review.json"))
    run_store = CampaignRunStore(path=os.path.join(root, "runs.json"))
    export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    package_service = CampaignPackageService(export_service=export_service)
    review_service = CampaignReviewService(prospect_store=prospect_store, export_service=export_service, review_store=review_store, package_service=package_service)
    run_service = CampaignRunService(run_store=run_store, prospect_store=prospect_store, job_store=job_store, project_store=project_store, review_store=review_store, export_service=export_service, review_service=review_service)
    run_handoff = SmartleadRunHandoffService(run_service=run_service, package_store=SmartleadRunPackageStore(path=os.path.join(root, "packages.json")), package_root=os.path.join(root, "handoff"))
    run_export = SmartleadRunExportService(run_handoff_service=run_handoff, hosted_asset_store=HostedAssetStore(path=os.path.join(root, "hosted.json")), mapping_store=PersonalizationFieldMappingStore(path=os.path.join(root, "mapping.json")), export_root=os.path.join(root, "exports"))
    assembly = CampaignAssemblyService(run_service=run_service, run_handoff_service=run_handoff, run_export_service=run_export, assembly_store=CampaignAssemblyStore(path=os.path.join(root, "assembly.json")))
    return locals()


def _ready(c, pid, headline="Trusted Local Roofing", contact_name="Alice Owner"):
    prospect = _prospect(prospect_id=pid, company_name=f"{pid.upper()} Roofing", email=f"{pid}@example.com", contact_name=contact_name, resolution_status=RESOLUTION_RESOLVED, resolution_confidence=CONFIDENCE_HIGH, resolved_profile_url=f"https://{pid}.example/alice-owner")
    c["prospect_store"].create(prospect)
    project = c["project_store"].create(company_name=prospect.company_name, website=prospect.website, name=pid)
    image_path = os.path.join(project.image_path, f"{pid}.png")
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write("mock")
    if "Fastest" in headline:
        project.metadata["source_evidence"] = "roofing contractor"
    concept = MockupConcept.create(image_path, "contractor", headline, "Call Today", 90, company_name=prospect.company_name)
    project.add_concept(concept)
    c["project_store"].save(project)
    job = ProspectGenerationJob(id=f"job-{pid}", prospect_id=pid, website=prospect.website, template="contractor", status="SUCCEEDED", project_id=project.id, result_path=image_path, opportunity_id=f"opp-{pid}", opportunity_context=OpportunityGenerationContext(opportunity_id=f"opp-{pid}", city="Castle Rock"))
    c["job_store"].upsert(job)
    c["job_store"].save()
    c["review_service"].approve(pid)
    return prospect, project, concept


def test_assembly_copy_blocked_and_warning_and_smartlead_export_safety(tmp_path):
    c = _runtime(tmp_path)
    _ready(c, "pass")
    _ready(c, "warn", headline="WARN Roofing | Roof Repair Near You")
    _ready(c, "block", headline="Fastest Roofing in Town")
    run = c["run_service"].create_run("Quality", ["pass", "warn", "block"])
    snapshot = c["assembly"].assemble_campaign(run.id).snapshot
    rows = {row.prospect_id: row for row in snapshot.readiness}
    assert rows["pass"].status == ASSEMBLY_STATUS_READY
    assert rows["warn"].status == ASSEMBLY_STATUS_WARNING
    assert rows["block"].status == ASSEMBLY_STATUS_BLOCKED

    result = c["assembly"].export_campaign(run.id, destination=os.path.join(str(tmp_path), "exports"))
    assert result.success
    with open(result.export_result.smartlead_csv_path, newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert {row["prospect_id"] for row in exported} == {"pass", "warn"}
    assert {row["company"] for row in exported} == {"PASS Roofing", "WARN Roofing"}


def test_assembly_unresolved_profile_warning(tmp_path):
    c = _runtime(tmp_path)
    prospect, _project, _concept = _ready(c, "unresolved")
    prospect.resolution_status = RESOLUTION_NOT_FOUND
    prospect.resolved_profile_url = ""
    prospect.resolution_confidence = ""
    c["prospect_store"].update(prospect)
    c["prospect_store"].save()
    run = c["run_service"].create_run("Profile", ["unresolved"])
    row = c["assembly"].assemble_campaign(run.id).snapshot.readiness[0]
    assert row.status == ASSEMBLY_STATUS_WARNING
    assert any(PERSON_PROFILE_UNRESOLVED in reason.code for reason in row.warning_reasons)


def test_campaign_review_exposes_concise_quality_reasons(tmp_path):
    c = _runtime(tmp_path)
    _ready(c, "review", headline="Fastest Roofing in Town")
    row = c["review_service"].list_rows(["review"])[0]
    assert row.technical_status == "BLOCKED"
    assert any("Unsupported superlative claim" in reason for reason in row.technical_reasons)