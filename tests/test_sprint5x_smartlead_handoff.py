from __future__ import annotations

import os
from collections import Counter

from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.controllers.smartlead_handoff_controller import SmartleadHandoffController
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.views.smartlead_handoff_page import SmartleadHandoffPage


def _runtime(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    review_store = CampaignReviewStore(path=os.path.join(str(tmp_path), "campaign_review.json"))
    run_store = CampaignRunStore(path=os.path.join(str(tmp_path), "campaign_runs.json"))
    export_service = CampaignExportService(
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
    )
    package_service = CampaignPackageService(export_service=export_service)
    review_service = CampaignReviewService(
        prospect_store=prospect_store,
        export_service=export_service,
        review_store=review_store,
        package_service=package_service,
    )
    run_service = CampaignRunService(
        run_store=run_store,
        prospect_store=prospect_store,
        job_store=job_store,
        project_store=project_store,
        review_store=review_store,
        export_service=export_service,
        review_service=review_service,
    )
    package_store = SmartleadRunPackageStore(path=os.path.join(str(tmp_path), "run_packages.json"))
    smartlead_service = SmartleadRunHandoffService(
        run_service=run_service,
        package_store=package_store,
        package_root=os.path.join(str(tmp_path), "smartlead_runs"),
    )
    return prospect_store, job_store, project_store, review_service, run_service, smartlead_service, package_store


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
                placement_type="bulletin",
                placement_name="Main St",
                location_name="Downtown",
            ),
        ),
    )
    job_store.upsert(job)
    job_store.save()
    return job


def test_run_scoping_and_ready_blocked_counts(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service, smartlead_service, _ = _runtime(tmp_path)
    ready = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    blocked = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="")
    unrelated = _prospect(prospect_store, prospect_id="c", company_name="C Co", email="c@example.com")
    project, concept = _project_with_concept(project_store, ready, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    review_service.approve("a")
    run = run_service.create_run("Alpha", ["a", "b"])

    context = smartlead_service.context_for_run(run.id)

    assert {row.prospect_id for row in context.rows} == {"a", "b"}
    assert "c" not in {row.prospect_id for row in context.rows}
    assert context.summary.packageable == 1
    assert context.summary.blocked == 1


def test_prepare_package_excludes_blocked_and_preserves_membership(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service, smartlead_service, _ = _runtime(tmp_path)
    ready = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    blocked = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="")
    project, concept = _project_with_concept(project_store, ready, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    review_service.approve("a")
    run = run_service.create_run("Alpha", ["a", "b"])
    before = list(run_service.get_run(run.id).prospect_ids)

    context = smartlead_service.prepare_package_for_run(run.id)

    assert list(run_service.get_run(run.id).prospect_ids) == before
    assert context.summary.packaged == 1
    assert context.summary.ready == 1
    assert any(row.prospect_id == "a" and row.packaged for row in context.rows)
    assert any(row.prospect_id == "b" and not row.packaged for row in context.rows)


def test_idempotent_rebuild_updates_single_run_record(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service, smartlead_service, package_store = _runtime(tmp_path)
    ready = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    project, concept = _project_with_concept(project_store, ready, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    review_service.approve("a")
    run = run_service.create_run("Alpha", ["a"])

    first = smartlead_service.prepare_package_for_run(run.id)
    second = smartlead_service.prepare_package_for_run(run.id)

    records = package_store.list()
    assert len(records) == 1
    assert records[0].campaign_run_id == run.id
    assert first.summary.packaged == 1
    assert second.summary.packaged == 1


def test_restart_persistence_and_run_switching(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service, smartlead_service, package_store = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    ap, ac = _project_with_concept(project_store, a, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
    review_service.approve("a")
    run_a = run_service.create_run("Alpha", ["a"])
    run_b = run_service.create_run("Beta", ["b"])
    smartlead_service.prepare_package_for_run(run_a.id)

    reloaded = SmartleadRunHandoffService(
        run_service=run_service,
        package_store=SmartleadRunPackageStore(path=package_store.path),
        package_root=os.path.join(str(tmp_path), "smartlead_runs"),
    )
    alpha = reloaded.context_for_run(run_a.id)
    beta = reloaded.context_for_run(run_b.id)

    assert alpha.summary.packaged == 1
    assert beta.summary.packaged == 0
    assert run_service.get_run(run_a.id).prospect_ids == ["a"]
    assert run_service.get_run(run_b.id).prospect_ids == ["b"]


def test_zero_ready_two_blocked_visible_outcome_and_membership_unchanged(tmp_path):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    prospect_store, job_store, project_store, review_service, run_service, smartlead_service, _ = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="")
    run = run_service.create_run("Test 1", ["a", "b"])
    before = list(run_service.get_run(run.id).prospect_ids)

    controller = SmartleadHandoffController(
        service=SmartleadHandoffService(),
        run_handoff_service=smartlead_service,
    )
    controller.open_run_context(run.id)
    context = controller.prepare_run_package()
    app.processEvents()

    assert context is not None
    assert context.summary.campaign_name == "Test 1"
    assert context.summary.ready == 0
    assert context.summary.blocked == 2
    assert context.summary.packaged == 0
    assert len(context.rows) == 2
    assert all(row.blockers for row in context.rows)
    assert all(not row.packaged for row in context.rows)
    assert list(run_service.get_run(run.id).prospect_ids) == before


def test_real_button_path_executes_once_per_click_and_does_not_recurse(tmp_path):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    prospect_store, job_store, project_store, review_service, run_service, smartlead_service, _ = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="")
    run = run_service.create_run("Test 1", ["a", "b"])

    controller = SmartleadHandoffController(
        service=SmartleadHandoffService(),
        run_handoff_service=smartlead_service,
    )
    page = SmartleadHandoffPage()
    page.set_controller(controller)
    controller.open_run_context(run.id)

    counts = Counter()
    sequence: list[str] = []

    original_handler = page._on_prepare_run_package
    original_prepare = controller.prepare_run_package
    original_refresh_pilots = controller.refresh_pilots
    original_set_run_context = page.set_run_context
    original_set_summary = page.set_summary
    original_set_rows = page.set_rows
    original_set_pilot_list = page.set_pilot_list

    def wrap(name, fn):
        def _wrapped(*args, **kwargs):
            counts[name] += 1
            sequence.append(name)
            if counts[name] > 5:
                raise AssertionError(f"unexpected recursion via {name}: {sequence}")
            return fn(*args, **kwargs)
        return _wrapped

    page._on_prepare_run_package = wrap("page._on_prepare_run_package", original_handler)
    controller.prepare_run_package = wrap("controller.prepare_run_package", original_prepare)
    controller.refresh_pilots = wrap("controller.refresh_pilots", original_refresh_pilots)
    page.set_run_context = wrap("page.set_run_context", original_set_run_context)
    page.set_summary = wrap("page.set_summary", original_set_summary)
    page.set_rows = wrap("page.set_rows", original_set_rows)
    page.set_pilot_list = wrap("page.set_pilot_list", original_set_pilot_list)

    page.prepare_run_package_button.click()
    app.processEvents()

    assert counts["page._on_prepare_run_package"] == 1
    assert counts["controller.prepare_run_package"] == 1
    assert counts["controller.refresh_pilots"] <= 1
    assert counts["page.set_pilot_list"] <= 1