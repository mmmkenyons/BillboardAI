from __future__ import annotations

import csv
import hashlib
import json
import os

from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import EXPORT_STATUS_BLOCKED, EXPORT_STATUS_WARNING, CampaignExportService
from gui.services.campaign_package import CampaignPackageService


def _runtime(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    export_service = CampaignExportService(
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
    )
    package_service = CampaignPackageService(export_service=export_service)
    return prospect_store, job_store, project_store, export_service, package_service


def _prospect(prospect_store: ProspectStore, **overrides) -> Prospect:
    prospect = Prospect(
        prospect_id=overrides.pop("prospect_id", "p1"),
        company_name=overrides.pop("company_name", "ABC Roofing"),
        website=overrides.pop("website", "https://abc.com"),
        email=overrides.pop("email", "owner@abc.com"),
        contact_name=overrides.pop("contact_name", "Alice Owner"),
        category=overrides.pop("category", "roofing"),
        city=overrides.pop("city", "Castle Rock"),
        state=overrides.pop("state", "CO"),
        **overrides,
    )
    prospect_store.create(prospect)
    prospect_store.save()
    return prospect


def _project_with_concept(project_store: ProjectStore, prospect: Prospect, image_name: str = "mockup.png", contents: str = "synthetic"):
    project = project_store.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
    image_path = os.path.join(project.image_path, image_name)
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write(contents)
    concept = MockupConcept.create(
        image_path=image_path,
        template="contractor",
        headline=f"{prospect.company_name} Billboard",
        cta="Call Today",
        quality_score=91.5,
        company_name=prospect.company_name,
    )
    project.add_concept(concept)
    project_store.save(project)
    return project, concept


def _job(job_store: ProspectGenerationStore, **overrides) -> ProspectGenerationJob:
    job = ProspectGenerationJob(
        id=overrides.pop("id", "job-1"),
        prospect_id=overrides.pop("prospect_id", "p1"),
        website=overrides.pop("website", "https://abc.com"),
        template=overrides.pop("template", "contractor"),
        status=overrides.pop("status", "SUCCEEDED"),
        project_id=overrides.pop("project_id", ""),
        result_path=overrides.pop("result_path", ""),
        opportunity_id=overrides.pop("opportunity_id", "opp-1"),
        location_id=overrides.pop("location_id", "loc-1"),
        placement_id=overrides.pop("placement_id", "pl-1"),
        opportunity_context=overrides.pop(
            "opportunity_context",
            OpportunityGenerationContext(
                opportunity_id="opp-1",
                location_id="loc-1",
                placement_id="pl-1",
                location_name="King Soopers #123",
                city="Castle Rock",
                state="CO",
                placement_name="Front Cart Corral A",
                placement_type="cart_corral",
            ),
        ),
        **overrides,
    )
    job_store.upsert(job)
    job_store.save()
    return job


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def test_ready_prospect_builds_valid_package(tmp_path):
    prospect_store, job_store, project_store, export_service, package_service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect, "mockup.png", contents="alpha")
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)

    result = package_service.build_package([prospect.prospect_id], str(tmp_path / "packages"), campaign_name="Denver Roofing August 2026")

    assert result.success is True
    assert os.path.isdir(result.package_directory)
    assert os.path.isfile(result.campaign_csv_path)
    assert os.path.isfile(result.validation_csv_path)
    assert os.path.isfile(result.manifest_path)
    rows = _read_csv(result.campaign_csv_path)
    assert len(rows) == 1
    assert rows[0]["prospect_id"] == prospect.prospect_id
    assert rows[0]["mockup_relative_path"].startswith("mockups/")
    validation = _read_csv(result.validation_csv_path)
    assert validation[0]["status"] == "READY"


def test_outreach_matches_canonical_export_and_preserves_snapshot_ids(tmp_path):
    prospect_store, job_store, project_store, export_service, package_service = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="opp")
    project, concept = _project_with_concept(project_store, prospect, "opp.png")
    _job(job_store, id="job-opp", prospect_id="opp", project_id=project.id, result_path=concept.image_path, opportunity_id="opp-77", location_id="loc-77", placement_id="pl-77")

    export_row = export_service.build_row("opp")
    result = package_service.build_package(["opp"], str(tmp_path / "packages"), campaign_name="snapshot")
    package_row = _read_csv(result.campaign_csv_path)[0]
    manifest = json.load(open(result.manifest_path, "r", encoding="utf-8"))

    assert package_row["email_subject"] == export_row.email_subject
    assert package_row["email_body"] == export_row.email_body
    assert package_row["opportunity_id"] == "opp-77"
    assert package_row["location_id"] == "loc-77"
    assert package_row["placement_id"] == "pl-77"
    assert manifest["prospects"][0]["opportunity_id"] == "opp-77"


def test_correct_mockup_copied_and_source_unchanged(tmp_path):
    prospect_store, job_store, project_store, _, package_service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect, "mockup.png", contents="original-bytes")
    source_hash = _sha256(concept.image_path)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)

    result = package_service.build_package([prospect.prospect_id], str(tmp_path / "packages"), campaign_name="copy-check")
    row = _read_csv(result.campaign_csv_path)[0]
    copied_path = os.path.join(result.package_directory, row["mockup_relative_path"].replace("/", os.sep))

    assert os.path.isfile(copied_path)
    assert _sha256(concept.image_path) == source_hash
    assert _sha256(copied_path) == source_hash


def test_missing_source_mockup_becomes_blocked_and_partial_batch_succeeds(tmp_path):
    prospect_store, job_store, project_store, _, package_service = _runtime(tmp_path)
    ready = _prospect(prospect_store, prospect_id="ready", company_name="Ready Co")
    warning = _prospect(prospect_store, prospect_id="warning", company_name="Warning Co", contact_name="", city="")
    missing = _prospect(prospect_store, prospect_id="missing", company_name="Missing Co")
    no_email = _prospect(prospect_store, prospect_id="blocked", company_name="Blocked Co", email="")

    ready_project, ready_concept = _project_with_concept(project_store, ready, "ready.png")
    warning_project, warning_concept = _project_with_concept(project_store, warning, "warning.png")
    missing_project, missing_concept = _project_with_concept(project_store, missing, "missing.png")
    os.remove(missing_concept.image_path)

    _job(job_store, id="job-ready", prospect_id="ready", project_id=ready_project.id, result_path=ready_concept.image_path)
    _job(job_store, id="job-warning", prospect_id="warning", project_id=warning_project.id, result_path=warning_concept.image_path, opportunity_id="", location_id="", placement_id="", opportunity_context=None)
    _job(job_store, id="job-missing", prospect_id="missing", project_id=missing_project.id, result_path=missing_concept.image_path)

    result = package_service.build_package(["ready", "warning", "missing", "blocked"], str(tmp_path / "packages"), campaign_name="mixed")

    assert result.success is True
    assert result.included_count == 2
    assert result.blocked_count == 2
    rows = _read_csv(result.campaign_csv_path)
    assert [row["prospect_id"] for row in rows] == ["ready", "warning"]
    validation = _read_csv(result.validation_csv_path)
    statuses = {row["prospect_id"]: row["status"] for row in validation}
    assert statuses == {"ready": "READY", "warning": "WARNING", "missing": "BLOCKED", "blocked": "BLOCKED"}
    reasons = {row["prospect_id"]: row["reason"] for row in validation}
    assert reasons["missing"] == "Source mockup file no longer exists."
    assert reasons["blocked"] == "Missing email."


def test_zero_exportable_prospects_creates_no_final_package(tmp_path):
    prospect_store, _, _, _, package_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="no-email", email="")
    destination = tmp_path / "packages"

    result = package_service.build_package(["no-email"], str(destination), campaign_name="zero")

    assert result.success is False
    assert result.package_directory == ""
    assert not destination.exists() or not any(destination.iterdir())


def test_package_folder_collision_and_asset_name_collision_are_safe(tmp_path):
    prospect_store, job_store, project_store, _, package_service = _runtime(tmp_path)
    first = _prospect(prospect_store, prospect_id="p-1", company_name="A/B Co")
    second = _prospect(prospect_store, prospect_id="p_1", company_name="A B Co")
    first_project, first_concept = _project_with_concept(project_store, first, "one.png")
    second_project, second_concept = _project_with_concept(project_store, second, "two.png")
    _job(job_store, id="job-1", prospect_id=first.prospect_id, project_id=first_project.id, result_path=first_concept.image_path)
    _job(job_store, id="job-2", prospect_id=second.prospect_id, project_id=second_project.id, result_path=second_concept.image_path)

    destination = tmp_path / "packages"
    first_result = package_service.build_package([first.prospect_id], str(destination), campaign_name="Collision Test")
    second_result = package_service.build_package([first.prospect_id, second.prospect_id], str(destination), campaign_name="Collision Test")

    assert os.path.basename(first_result.package_directory) == "Collision_Test"
    assert os.path.basename(second_result.package_directory) == "Collision_Test_2"
    rows = _read_csv(second_result.campaign_csv_path)
    assert rows[0]["mockup_relative_path"] != rows[1]["mockup_relative_path"]


def test_deterministic_selected_order_manifest_totals_and_cross_prospect_isolation(tmp_path):
    prospect_store, job_store, project_store, _, package_service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="Alpha Co", email="a@example.com", city="Denver")
    b = _prospect(prospect_store, prospect_id="b", company_name="Bravo Co", email="b@example.com", city="Austin", category="dentist")
    ap, ac = _project_with_concept(project_store, a, "a.png")
    bp, bc = _project_with_concept(project_store, b, "b.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
    _job(job_store, id="job-b", prospect_id="b", project_id=bp.id, result_path=bc.image_path, opportunity_context=OpportunityGenerationContext(city="Austin", state="TX", placement_type="storefront"))

    result = package_service.build_package(["b", "a", "b"], str(tmp_path / "packages"), campaign_name="ordered")
    rows = _read_csv(result.campaign_csv_path)
    manifest = json.load(open(result.manifest_path, "r", encoding="utf-8"))

    assert [row["prospect_id"] for row in rows] == ["b", "a"]
    assert [entry["prospect_id"] for entry in manifest["prospects"]] == ["b", "a"]
    assert manifest["total_selected"] == 2
    assert manifest["total_exportable"] == 2
    assert "Bravo Co" in rows[0]["email_body"] and "Alpha Co" not in rows[0]["email_body"]
    assert "Alpha Co" in rows[1]["email_body"] and "Bravo Co" not in rows[1]["email_body"]


def test_generic_and_legacy_package_behavior_and_no_internal_metadata_leakage(tmp_path):
    prospect_store, job_store, project_store, _, package_service = _runtime(tmp_path)
    generic = _prospect(prospect_store, prospect_id="g", contact_name="", city="", company_name="Generic Co")
    legacy = _prospect(prospect_store, prospect_id="l", company_name="Legacy Co", city="Castle Rock")
    gp, gc = _project_with_concept(project_store, generic, "generic.png")
    lp, lc = _project_with_concept(project_store, legacy, "legacy.png")
    _job(job_store, id="job-g", prospect_id="g", project_id=gp.id, result_path=gc.image_path, opportunity_id="", location_id="", placement_id="", opportunity_context=None, metadata={"secret": "job-secret-789"})
    _job(job_store, id="job-l", prospect_id="l", project_id=lp.id, result_path=lc.image_path, opportunity_id="", location_id="", placement_id="", opportunity_context=None)

    result = package_service.build_package(["g", "l"], str(tmp_path / "packages"), campaign_name="legacy-generic")
    rows = _read_csv(result.campaign_csv_path)
    validation = _read_csv(result.validation_csv_path)

    row_g = next(row for row in rows if row["prospect_id"] == "g")
    row_l = next(row for row in rows if row["prospect_id"] == "l")
    validation_g = next(row for row in validation if row["prospect_id"] == "g")
    assert validation_g["status"] == "WARNING"
    assert row_g["opportunity_id"] == ""
    assert row_l["opportunity_id"] == ""
    assert "Castle Rock" in row_l["email_body"]
    for token in ["job-secret-789", "loc-secret-123", "FOLLOW_UP", "STRONG MATCH"]:
        assert token not in row_g["email_subject"]
        assert token not in row_g["email_body"]


def test_package_build_is_read_only_and_no_recomputation(tmp_path):
    prospect_store, job_store, project_store, _, package_service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    before_prospects = prospect_store.list()
    before_jobs = [job.to_dict() for job in job_store.list()]
    before_projects = [project.id for project in project_store.list()]

    result = package_service.build_package([prospect.prospect_id], str(tmp_path / "packages"), campaign_name="readonly")

    assert result.success is True
    assert [job.to_dict() for job in job_store.list()] == before_jobs
    assert [project.id for project in project_store.list()] == before_projects
    assert [item.prospect_id for item in prospect_store.list()] == [item.prospect_id for item in before_prospects]