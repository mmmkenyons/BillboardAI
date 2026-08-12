from __future__ import annotations

import csv
import hashlib
import json
import os

from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_handoff import CampaignFieldMapping, SmartleadHandoffProfile
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.smartlead_handoff import SmartleadHandoffService


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
    review_store = CampaignReviewStore(path=os.path.join(str(tmp_path), "campaign_review.json"))
    review_service = CampaignReviewService(
        prospect_store=prospect_store,
        export_service=export_service,
        review_store=review_store,
        package_service=package_service,
    )
    handoff_service = SmartleadHandoffService()
    return prospect_store, job_store, project_store, review_service, handoff_service, review_store


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


def _project_with_concept(project_store: ProjectStore, prospect: Prospect, image_name: str = "mockup.png"):
    project = project_store.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
    image_path = os.path.join(project.image_path, image_name)
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write(prospect.prospect_id)
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
                city="Castle Rock",
                state="CO",
                location_name="Main Street",
                placement_name="Front",
                placement_type="cart_corral",
            ),
        ),
        metadata=overrides.pop("metadata", {}),
    )
    job_store.upsert(job)
    job_store.save()
    return job


def _build_package(review_service: CampaignReviewService, prospect_ids: list[str], destination: str):
    for prospect_id in prospect_ids:
        review_service.approve(prospect_id)
    result = review_service.build_approved_package(prospect_ids, destination, "approved_campaign")
    assert result.success is True
    return result


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_default_profile_and_mapping_contract():
    profile = SmartleadHandoffProfile.default()
    assert profile.profile_version == "5P"
    assert profile.required_fields == ("email", "email_subject", "email_body")
    mapping = {item.source_field: item.destination_field for item in profile.field_mapping}
    assert mapping["email"] == "email"
    assert mapping["mockup_relative_path"] == "mockup_path"


def test_valid_ready_row_and_files_created(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    project, concept = _project_with_concept(project_store, prospect, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    package_result = _build_package(review_service, ["a"], str(tmp_path / "packages"))

    result = handoff_service.prepare_handoff(package_result.package_directory)

    assert result.success is True
    assert os.path.isfile(result.smartlead_csv_path)
    assert os.path.isfile(result.mapping_path)
    assert os.path.isfile(result.preflight_path)
    assert os.path.isfile(result.manifest_path)
    rows = _read_csv(result.smartlead_csv_path)
    assert rows[0]["email"] == "a@example.com"
    assert rows[0]["mockup_path"].startswith("mockups/")


def test_missing_and_malformed_email_and_subject_body_blocked(tmp_path):
    invalids = ["", "abc", "abc@", "@example.com", "abc @example.com"]
    for idx, email in enumerate(invalids, start=1):
        prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path / f"case_{idx}")
        prospect = _prospect(prospect_store, prospect_id="x", company_name="X Co", email="valid@example.com")
        project, concept = _project_with_concept(project_store, prospect, "x.png")
        _job(job_store, id="job-x", prospect_id="x", project_id=project.id, result_path=concept.image_path)
        package_result = _build_package(review_service, ["x"], str((tmp_path / f"case_{idx}") / "packages"))
        campaign_path = package_result.campaign_csv_path
        rows = _read_csv(campaign_path)
        rows[0]["email"] = email
        rows[0]["email_subject"] = ""
        rows[0]["email_body"] = ""
        with open(campaign_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        result = handoff_service.prepare_handoff(package_result.package_directory)

        assert result.success is False
        assert result.rows[0].status == "BLOCKED"
        reason_text = "; ".join(result.rows[0].reasons)
        assert "Email failed local format sanity validation." in reason_text
        assert "Missing required field: email_subject." in reason_text
        assert "Missing required field: email_body." in reason_text
        assert result.smartlead_csv_path == ""


def test_duplicate_email_conflict_and_zero_ready_behavior(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="shared@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="shared@example.com")
    for prospect, image in [(a, "a.png"), (b, "b.png")]:
        project, concept = _project_with_concept(project_store, prospect, image)
        _job(job_store, id=f"job-{prospect.prospect_id}", prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    package_result = _build_package(review_service, ["a", "b"], str(tmp_path / "packages"))

    result = handoff_service.prepare_handoff(package_result.package_directory)

    assert result.success is False
    assert {row.status for row in result.rows} == {"CONFLICT"}
    assert not os.path.exists(os.path.join(result.handoff_directory, "smartlead.csv"))


def test_excluded_and_needs_review_rows_omitted_and_warning_included(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    ready = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    warning = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com", contact_name="")
    excluded = _prospect(prospect_store, prospect_id="c", company_name="C Co", email="c@example.com")
    needs_review = _prospect(prospect_store, prospect_id="d", company_name="D Co", email="d@example.com")
    for prospect in [ready, warning, excluded, needs_review]:
        project, concept = _project_with_concept(project_store, prospect, f"{prospect.prospect_id}.png")
        _job(job_store, id=f"job-{prospect.prospect_id}", prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    review_service.approve("a")
    review_service.approve("b")
    review_service.exclude("c")
    review_service.mark_needs_review("d")
    package_result = review_service.build_approved_package(["a", "b", "c", "d"], str(tmp_path / "packages"), "approved_campaign")

    result = handoff_service.prepare_handoff(package_result.package_directory)

    assert {row.prospect_id for row in result.rows} == {"a", "b"}
    final_rows = _read_csv(result.smartlead_csv_path)
    assert [row["prospect_id"] for row in final_rows] == ["a", "b"]


def test_mockup_relative_path_preserved_and_missing_asset_blocked(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    project, concept = _project_with_concept(project_store, prospect, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    package_result = _build_package(review_service, ["a"], str(tmp_path / "packages"))
    first = handoff_service.prepare_handoff(package_result.package_directory)
    assert first.rows[0].mapped_fields["mockup_path"].startswith("mockups/")
    os.remove(os.path.join(package_result.package_directory, first.rows[0].mapped_fields["mockup_path"].replace("/", os.sep)))

    second = handoff_service.prepare_handoff(package_result.package_directory)

    assert second.rows[0].status == "BLOCKED"
    assert "Packaged mockup asset reference is missing." in second.rows[0].reasons


def test_cross_prospect_isolation_and_internal_metadata_not_leaked(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="Alpha Co", email="a@example.com", city="Castle Rock")
    b = _prospect(prospect_store, prospect_id="b", company_name="Bravo Co", email="b@example.com", city="Austin", state="TX")
    for prospect, image, city, placement in [(a, "a.png", "Castle Rock", "cart_corral"), (b, "b.png", "Austin", "storefront")]:
        project, concept = _project_with_concept(project_store, prospect, image)
        _job(
            job_store,
            id=f"job-{prospect.prospect_id}",
            prospect_id=prospect.prospect_id,
            project_id=project.id,
            result_path=concept.image_path,
            opportunity_id=f"opp-{prospect.prospect_id}",
            location_id=f"loc-{prospect.prospect_id}",
            placement_id=f"pl-{prospect.prospect_id}",
            opportunity_context=OpportunityGenerationContext(
                opportunity_id=f"opp-{prospect.prospect_id}",
                location_id=f"loc-{prospect.prospect_id}",
                placement_id=f"pl-{prospect.prospect_id}",
                city=city,
                state=prospect.state,
                placement_name="Front",
                placement_type=placement,
            ),
        )
    package_result = _build_package(review_service, ["a", "b"], str(tmp_path / "packages"))

    result = handoff_service.prepare_handoff(package_result.package_directory)

    output = _read_csv(result.smartlead_csv_path)
    row_a = next(row for row in output if row["prospect_id"] == "a")
    row_b = next(row for row in output if row["prospect_id"] == "b")
    assert "Bravo Co" not in row_a["email_body"]
    assert "Alpha Co" not in row_b["email_body"]
    for row in output:
        for token in [row.get("project_id", ""), row.get("generation_job_id", "")]:
            if token:
                assert token not in row["email_body"]


def test_field_mapping_rename_disable_duplicate_rejected_and_deterministic_order(tmp_path):
    profile = SmartleadHandoffProfile.default()
    renamed = SmartleadHandoffProfile(
        profile_version=profile.profile_version,
        name=profile.name,
        required_fields=profile.required_fields,
        optional_fields=profile.optional_fields,
        created_at=profile.created_at,
        field_mapping=tuple(
            CampaignFieldMapping(item.source_field, "company_name" if item.source_field == "company" else item.destination_field, item.required, False if item.source_field == "contact_name" else item.enabled)
            for item in profile.field_mapping
        ),
    )
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    project, concept = _project_with_concept(project_store, prospect, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    package_result = _build_package(review_service, ["a"], str(tmp_path / "packages"))
    result = handoff_service.prepare_handoff(package_result.package_directory, profile=renamed)
    rows = _read_csv(result.smartlead_csv_path)
    assert list(rows[0].keys())[:6] == ["email", "first_name", "email_subject", "email_body", "mockup_path", "company_name"] or "company_name" in rows[0]
    assert "contact_name" not in rows[0]

    duplicate_profile = SmartleadHandoffProfile(
        profile_version=profile.profile_version,
        name=profile.name,
        required_fields=profile.required_fields,
        optional_fields=profile.optional_fields,
        created_at=profile.created_at,
        field_mapping=tuple(
            list(profile.field_mapping[:-1]) + [CampaignFieldMapping("generation_job_id", "project_id", required=False, enabled=True)]
        ),
    )
    duplicate_result = handoff_service.prepare_handoff(package_result.package_directory, profile=duplicate_profile)
    assert duplicate_result.success is False
    assert "Duplicate destination mapping" in duplicate_result.message


def test_multiline_csv_round_trip_and_canonical_files_unchanged(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, review_store = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="a", company_name="A, Co", email="a@example.com")
    project, concept = _project_with_concept(project_store, prospect, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    package_result = _build_package(review_service, ["a"], str(tmp_path / "packages"))
    before_campaign = _sha256(package_result.campaign_csv_path)
    before_manifest = _sha256(package_result.manifest_path)
    before_review = _sha256(review_store.path)
    result = handoff_service.prepare_handoff(package_result.package_directory)

    output_rows = _read_csv(result.smartlead_csv_path)
    assert "\n\n" in output_rows[0]["email_body"]
    assert _sha256(package_result.campaign_csv_path) == before_campaign
    assert _sha256(package_result.manifest_path) == before_manifest
    assert _sha256(review_store.path) == before_review
