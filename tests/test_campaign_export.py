from __future__ import annotations

import csv
import os

from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_SUCCEEDED,
    OpportunityGenerationContext,
    ProspectGenerationJob,
)
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import (
    CSV_COLUMNS,
    EXPORT_STATUS_BLOCKED,
    EXPORT_STATUS_READY,
    EXPORT_STATUS_WARNING,
    CampaignExportService,
)


def _runtime(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    service = CampaignExportService(
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
    )
    return prospect_store, job_store, project_store, service


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
        handle.write("synthetic")
    concept = MockupConcept.create(
        image_path=image_path,
        template="contractor",
        headline="Roofing Billboard",
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
        status=overrides.pop("status", JOB_STATUS_SUCCEEDED),
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


def test_ready_prospect_exports(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, project_id=project.id, result_path=concept.image_path)
    eligibility = service.check_eligibility(prospect.prospect_id)
    assert eligibility.status == EXPORT_STATUS_READY
    row = service.build_row(prospect.prospect_id)
    assert row.email == "owner@abc.com"
    assert row.opportunity_id == "opp-1"
    assert row.mockup_path == concept.image_path


def test_missing_email_blocked(tmp_path):
    prospect_store, _, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store, email="")
    eligibility = service.check_eligibility(prospect.prospect_id)
    assert eligibility.status == EXPORT_STATUS_BLOCKED


def test_no_successful_generation_blocked(tmp_path):
    prospect_store, job_store, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    _job(job_store, prospect_id=prospect.prospect_id, status=JOB_STATUS_FAILED, opportunity_context=None)
    assert service.check_eligibility(prospect.prospect_id).status == EXPORT_STATUS_BLOCKED


def test_queued_job_alone_blocked(tmp_path):
    prospect_store, job_store, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    _job(job_store, prospect_id=prospect.prospect_id, status=JOB_STATUS_QUEUED, opportunity_context=None)
    assert service.check_eligibility(prospect.prospect_id).status == EXPORT_STATUS_BLOCKED


def test_older_success_survives_newer_failure(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, id="job-1", prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    _job(job_store, id="job-2", prospect_id=prospect.prospect_id, status=JOB_STATUS_FAILED, opportunity_context=None)
    assert service.build_row(prospect.prospect_id).generation_job_id == "job-1"


def test_newest_usable_success_selected(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project1, concept1 = _project_with_concept(project_store, prospect, "old.png")
    project2, concept2 = _project_with_concept(project_store, prospect, "new.png")
    _job(job_store, id="job-1", prospect_id=prospect.prospect_id, project_id=project1.id, result_path=concept1.image_path)
    newer = _job(job_store, id="job-2", prospect_id=prospect.prospect_id, project_id=project2.id, result_path=concept2.image_path)
    newer.opportunity_id = "opp-2"
    newer.location_id = "loc-2"
    newer.placement_id = "pl-2"
    job_store.upsert(newer)
    job_store.save()
    row = service.build_row(prospect.prospect_id)
    assert row.generation_job_id == "job-2"
    assert row.opportunity_id == "opp-2"


def test_generic_generation_leaves_opportunity_fields_blank(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    eligibility_job = _job(
        job_store,
        prospect_id=prospect.prospect_id,
        project_id=project.id,
        result_path=concept.image_path,
        opportunity_id="",
        location_id="",
        placement_id="",
        opportunity_context=None,
    )
    row = service.build_row(prospect.prospect_id)
    assert row.opportunity_id == ""
    assert row.location_id == ""
    assert row.placement_id == ""
    assert service.check_eligibility(prospect.prospect_id).status == EXPORT_STATUS_WARNING
    assert eligibility_job.id == row.generation_job_id


def test_csv_column_order_and_escaping(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store, company_name='ABC, Roofing', contact_name='Alice Owner')
    project, concept = _project_with_concept(project_store, prospect)
    concept.headline = 'Line 1,\nLine 2'
    project_store.save(project)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    output_path = os.path.join(str(tmp_path), 'campaign.csv')
    service.export_csv([prospect.prospect_id], output_path)
    with open(output_path, 'r', encoding='utf-8', newline='') as handle:
        lines = handle.read().splitlines()
    assert lines[0].split(',') == list(CSV_COLUMNS)
    with open(output_path, 'r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert rows[0]['company'] == 'ABC, Roofing'
    assert rows[0]['headline'] == 'Line 1,\nLine 2'


def test_no_duplicate_prospects_and_deterministic_ordering(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect_b = _prospect(prospect_store, prospect_id='b', company_name='B Co', email='b@example.com')
    prospect_a = _prospect(prospect_store, prospect_id='a', company_name='A Co', email='a@example.com')
    for prospect in (prospect_a, prospect_b):
        project, concept = _project_with_concept(project_store, prospect, f'{prospect.prospect_id}.png')
        _job(job_store, id=f'job-{prospect.prospect_id}', prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    rows = service.build_rows(['b', 'a', 'a'])
    assert [row.prospect_id for row in rows] == ['a', 'b']


def test_cross_prospect_isolation(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect_a = _prospect(prospect_store, prospect_id='a', company_name='A Co', email='a@example.com')
    prospect_b = _prospect(prospect_store, prospect_id='b', company_name='B Co', email='b@example.com')
    project_a, concept_a = _project_with_concept(project_store, prospect_a, 'a.png')
    project_b, concept_b = _project_with_concept(project_store, prospect_b, 'b.png')
    _job(job_store, id='job-a', prospect_id='a', project_id=project_a.id, result_path=concept_a.image_path)
    _job(job_store, id='job-b', prospect_id='b', project_id=project_b.id, result_path=concept_b.image_path)
    row_a = service.build_row('a')
    row_b = service.build_row('b')
    assert row_a.company == 'A Co'
    assert row_b.company == 'B Co'
    assert row_a.mockup_path.endswith('a.png')
    assert row_b.mockup_path.endswith('b.png')
    assert 'B Co' not in row_a.email_body
    assert 'A Co' not in row_b.email_body


def test_legacy_pre_5k_job_compatibility(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(
        job_store,
        prospect_id=prospect.prospect_id,
        project_id=project.id,
        result_path=concept.image_path,
        opportunity_id='',
        location_id='',
        placement_id='',
        opportunity_context=None,
    )
    row = service.build_row(prospect.prospect_id)
    assert row.project_id == project.id
    assert row.opportunity_id == ''
    assert row.email_subject == 'Quick idea for ABC Roofing'
    assert 'Castle Rock' in row.email_body
    assert 'placement' not in row.email_body


def test_csv_includes_email_columns_and_multiline_round_trip(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store, company_name="ABC, Roofing")
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    output_path = os.path.join(str(tmp_path), "campaign.csv")
    service.export_csv([prospect.prospect_id], output_path)
    with open(output_path, 'r', encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert 'email_subject' in rows[0]
    assert 'email_body' in rows[0]
    assert rows[0]['email_subject'] == 'Quick idea for ABC, Roofing'
    assert '\n\n' in rows[0]['email_body']


def test_preview_is_read_only_and_non_mutating(tmp_path):
    prospect_store, job_store, project_store, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    before_jobs = len(job_store.list())
    before_projects = len(project_store.list())
    previews = service.preview_rows([prospect.prospect_id])
    assert previews[0].status == EXPORT_STATUS_READY
    assert len(job_store.list()) == before_jobs
    assert len(project_store.list()) == before_projects