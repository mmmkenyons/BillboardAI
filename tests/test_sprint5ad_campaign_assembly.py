"""Sprint 5AD deterministic tests for bulk campaign assembly."""
from __future__ import annotations

import csv
import os

from gui.models.campaign_assembly import ASSEMBLY_STATUS_BLOCKED, ASSEMBLY_STATUS_EXCLUDED, ASSEMBLY_STATUS_READY, ASSEMBLY_STATUS_WARNING, CampaignAssemblyStore
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.mockup_concept import MockupConcept
from gui.models.personalization_field_catalog import PersonalizationFieldMapping, PersonalizationFieldMappingStore, default_personalization_mapping
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_assembly import CampaignAssemblyService, REASON_MISSING_EMAIL, REASON_OPERATOR_EXCLUDED
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.services.smartlead_run_export import SmartleadRunExportService
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


def _runtime(tmp_path):
    root = str(tmp_path)
    prospect_store = ProspectStore(path=os.path.join(root, "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
    project_store = ProjectStore(root=os.path.join(root, "projects"))
    review_store = CampaignReviewStore(path=os.path.join(root, "campaign_review.json"))
    run_store = CampaignRunStore(path=os.path.join(root, "campaign_runs.json"))
    export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    package_service = CampaignPackageService(export_service=export_service)
    review_service = CampaignReviewService(prospect_store=prospect_store, export_service=export_service, review_store=review_store, package_service=package_service)
    run_service = CampaignRunService(run_store=run_store, prospect_store=prospect_store, job_store=job_store, project_store=project_store, review_store=review_store, export_service=export_service, review_service=review_service)
    run_handoff = SmartleadRunHandoffService(run_service=run_service, package_store=SmartleadRunPackageStore(path=os.path.join(root, "run_packages.json")), package_root=os.path.join(root, "smartlead_runs"))
    mapping_store = PersonalizationFieldMappingStore(path=os.path.join(root, "field_mapping.json"))
    run_export = SmartleadRunExportService(run_handoff_service=run_handoff, hosted_asset_store=HostedAssetStore(path=os.path.join(root, "hosted.json")), mapping_store=mapping_store, export_root=os.path.join(root, "exports"))
    assembly_store = CampaignAssemblyStore(path=os.path.join(root, "assemblies.json"))
    assembly = CampaignAssemblyService(run_service=run_service, run_handoff_service=run_handoff, run_export_service=run_export, assembly_store=assembly_store)
    return locals()


def _prospect(c, pid, email=None, contact_name="Alice Owner", city="Castle Rock"):
    if email is None:
        email = f"{pid}@example.com"
    prospect = Prospect(prospect_id=pid, company_name=f"{pid.upper()} Co", website=f"https://{pid}.example.com", email=email, contact_name=contact_name, category="roofing", city=city, state="CO")
    c["prospect_store"].create(prospect)
    c["prospect_store"].save()
    return prospect


def _project(c, prospect, image_name="mock.png", headline="Great Billboard", cta="Call Today"):
    project = c["project_store"].create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
    image_path = os.path.join(project.image_path, image_name)
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write(prospect.prospect_id)
    concept = MockupConcept.create(image_path=image_path, template="contractor", headline=headline, cta=cta, quality_score=90, company_name=prospect.company_name)
    project.add_concept(concept)
    c["project_store"].save(project)
    return project, concept


def _job(c, prospect, project, concept, status="SUCCEEDED"):
    job = ProspectGenerationJob(
        id=f"job-{prospect.prospect_id}",
        prospect_id=prospect.prospect_id,
        website=prospect.website,
        template="contractor",
        status=status,
        project_id=project.id if project else "",
        result_path=concept.image_path if concept else "",
        opportunity_id="opp-1",
        location_id="loc-1",
        placement_id="pl-1",
        opportunity_context=OpportunityGenerationContext(opportunity_id="opp-1", location_id="loc-1", placement_id="pl-1", city="Castle Rock", state="CO", placement_name="I-25", placement_type="Billboard"),
    )
    c["job_store"].upsert(job)
    c["job_store"].save()
    return job


def _ready(c, pid, **kwargs):
    prospect = _prospect(c, pid, **{k: v for k, v in kwargs.items() if k in {"email", "contact_name", "city"}})
    project, concept = _project(c, prospect, headline=kwargs.get("headline", "Great Billboard"), cta=kwargs.get("cta", "Call Today"))
    _job(c, prospect, project, concept)
    c["review_service"].approve(pid)
    return prospect


def _rows(snapshot):
    return {row.prospect_id: row for row in snapshot.readiness}


def test_all_ready_batch_exports_existing_smartlead_path(tmp_path):
    c = _runtime(tmp_path)
    _ready(c, "a")
    _ready(c, "b")
    run = c["run_service"].create_run("Alpha", ["a", "b"])
    result = c["assembly"].export_campaign(run.id, destination=os.path.join(str(tmp_path), "final"))
    assert result.success
    assert result.summary.exportable == 2
    assert os.path.isfile(result.export_result.smartlead_csv_path)
    with open(result.export_result.smartlead_csv_path, newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 2


def test_mixed_readiness_warning_blocked_excluded_and_reason_counts(tmp_path):
    c = _runtime(tmp_path)
    _ready(c, "ready")
    _ready(c, "warn", contact_name="", city="")
    _prospect(c, "noemail", email="")
    _ready(c, "excluded")
    c["review_service"].exclude("excluded")
    run = c["run_service"].create_run("Mixed", ["ready", "warn", "noemail", "excluded"])
    result = c["assembly"].assemble_campaign(run.id)
    rows = _rows(result.snapshot)
    assert rows["ready"].status == ASSEMBLY_STATUS_READY
    assert rows["warn"].status == ASSEMBLY_STATUS_WARNING
    assert rows["noemail"].status == ASSEMBLY_STATUS_BLOCKED
    assert rows["excluded"].status == ASSEMBLY_STATUS_EXCLUDED
    assert result.summary.exportable == 2
    assert result.summary.reason_counts[REASON_MISSING_EMAIL] == 1
    assert result.summary.reason_counts[REASON_OPERATOR_EXCLUDED] == 1


def test_missing_generation_and_missing_mockup_block(tmp_path):
    c = _runtime(tmp_path)
    _prospect(c, "nogeneration", email="x@example.com")
    c["review_service"].approve("nogeneration")
    missing = _ready(c, "missingmock")
    job = c["job_store"].get("job-missingmock")
    os.remove(job.result_path)
    run = c["run_service"].create_run("Blocked", ["nogeneration", "missingmock"])
    rows = _rows(c["assembly"].assemble_campaign(run.id).snapshot)
    assert rows["nogeneration"].status == ASSEMBLY_STATUS_BLOCKED
    assert rows["missingmock"].status == ASSEMBLY_STATUS_BLOCKED


def test_blocked_cannot_be_force_included_and_exclusion_reinclusion_persist(tmp_path):
    c = _runtime(tmp_path)
    _ready(c, "a")
    _prospect(c, "blocked", email="")
    run = c["run_service"].create_run("Include", ["a", "blocked"])
    c["assembly"].set_excluded(run.id, "a", True)
    assert c["prospect_store"].get("a") is not None
    reloaded = CampaignAssemblyService(run_service=c["run_service"], run_handoff_service=c["run_handoff"], run_export_service=c["run_export"], assembly_store=CampaignAssemblyStore(path=c["assembly_store"].path))
    assert _rows(reloaded.latest_snapshot(run.id))["a"].status == ASSEMBLY_STATUS_EXCLUDED
    result = c["assembly"].set_excluded(run.id, "a", False)
    assert result.success
    assert _rows(result.snapshot)["a"].exportable
    blocked = c["assembly"].set_excluded(run.id, "blocked", False)
    assert not blocked.success


def test_sprint5ac_optional_mapping_honored_and_blank_optional_nonblocking(tmp_path):
    c = _runtime(tmp_path)
    _ready(c, "a")
    mapping = default_personalization_mapping()
    mapping.append(PersonalizationFieldMapping("professional_title", "professional_title", enabled=True, position=999))
    c["mapping_store"].save(mapping)
    run = c["run_service"].create_run("Mapping", ["a"])
    result = c["assembly"].export_campaign(run.id, destination=os.path.join(str(tmp_path), "exports"))
    assert result.success
    rows = _rows(result.snapshot)
    assert rows["a"].status == ASSEMBLY_STATUS_WARNING
    with open(result.export_result.smartlead_csv_path, newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert "professional_title" in exported[0]


def test_no_side_effect_services_called(tmp_path, monkeypatch):
    c = _runtime(tmp_path)
    _ready(c, "a")
    run = c["run_service"].create_run("No Side Effects", ["a"])
    calls = []
    monkeypatch.setattr("gui.services.prospect_generation.ProspectGenerationService.enqueue", lambda *a, **k: calls.append("generate"), raising=False)
    monkeypatch.setattr("gui.services.profile_resolver.ProfileResolverService.resolve", lambda *a, **k: calls.append("resolve"), raising=False)
    monkeypatch.setattr("gui.services.smartlead_api.SmartleadApiClient.request", lambda *a, **k: calls.append("smartlead"), raising=False)
    c["assembly"].export_campaign(run.id, destination=os.path.join(str(tmp_path), "exports"))
    assert calls == []


def test_batch_size_sanity_and_restart_persistence(tmp_path):
    c = _runtime(tmp_path)
    ids = []
    for index in range(100):
        pid = f"p{index:03d}"
        ids.append(pid)
        _ready(c, pid)
    run = c["run_service"].create_run("Hundred", ids)
    result = c["assembly"].assemble_campaign(run.id)
    assert result.summary.total_prospects == 100
    assert result.summary.exportable == 100
    reloaded = CampaignAssemblyStore(path=c["assembly_store"].path)
    assert len(reloaded.get(run.id).readiness) == 100