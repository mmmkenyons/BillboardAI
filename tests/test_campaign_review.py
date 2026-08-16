from __future__ import annotations

import os

from gui.models.campaign_review import (
    CAMPAIGN_REVIEW_STATUS_APPROVED,
    CAMPAIGN_REVIEW_STATUS_EXCLUDED,
    CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW,
)
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import EXPORT_STATUS_BLOCKED, EXPORT_STATUS_READY, EXPORT_STATUS_WARNING, CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import (
    REVIEW_FILTER_APPROVED,
    REVIEW_FILTER_BLOCKED,
    REVIEW_FILTER_EXCLUDED,
    REVIEW_FILTER_NEEDS_REVIEW,
    CampaignReviewService,
)
from gui.services.workflow_presentation import format_blocker, format_status


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
    return prospect_store, job_store, project_store, export_service, package_service, review_store, review_service


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
                location_name="King Soopers",
                placement_name="Front Entrance",
                placement_type="cart_corral",
            ),
        ),
        metadata=overrides.pop("metadata", {}),
    )
    job_store.upsert(job)
    job_store.save()
    return job


def test_default_review_status(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    row = service.list_rows([prospect.prospect_id])[0]
    assert row.review_status == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
    assert row.technical_status == EXPORT_STATUS_READY


def test_approve_exclude_and_needs_review(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    assert service.approve(prospect.prospect_id).status == CAMPAIGN_REVIEW_STATUS_APPROVED
    assert service.exclude(prospect.prospect_id).status == CAMPAIGN_REVIEW_STATUS_EXCLUDED
    assert service.mark_needs_review(prospect.prospect_id).status == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW


def test_note_and_restart_persistence(tmp_path):
    prospect_store, job_store, project_store, export_service, package_service, review_store, service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="A Co")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co")
    c = _prospect(prospect_store, prospect_id="c", company_name="C Co")
    for prospect in [a, b, c]:
        project, concept = _project_with_concept(project_store, prospect, f"{prospect.prospect_id}.png")
        _job(job_store, id=f"job-{prospect.prospect_id}", prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    service.approve("a")
    service.exclude("b")
    service.mark_needs_review("c")
    service.update_note("a", "strong fit")

    reloaded = CampaignReviewService(
        prospect_store=prospect_store,
        export_service=export_service,
        review_store=CampaignReviewStore(path=review_store.path),
        package_service=package_service,
    )
    rows = {row.prospect_id: row for row in reloaded.list_rows(["a", "b", "c"])}
    assert rows["a"].review_status == CAMPAIGN_REVIEW_STATUS_APPROVED
    assert rows["a"].review_note == "strong fit"
    assert rows["b"].review_status == CAMPAIGN_REVIEW_STATUS_EXCLUDED
    assert rows["c"].review_status == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW


def test_decision_isolation_and_canonical_export_data(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com", city="Austin", state="TX", category="dentist")
    ap, ac = _project_with_concept(project_store, a, "a.png")
    bp, bc = _project_with_concept(project_store, b, "b.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
    _job(job_store, id="job-b", prospect_id="b", project_id=bp.id, result_path=bc.image_path, opportunity_context=OpportunityGenerationContext(city="Austin", state="TX", location_name="HEB", placement_name="Storefront", placement_type="storefront"))
    service.approve("a")
    rows = {row.prospect_id: row for row in service.list_rows(["a", "b"])}
    assert rows["a"].review_status == CAMPAIGN_REVIEW_STATUS_APPROVED
    assert rows["b"].review_status == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
    assert rows["a"].company == "A Co"
    assert rows["b"].company == "B Co"
    assert "B Co" not in rows["a"].email_body
    assert "A Co" not in rows["b"].email_body
    assert rows["b"].opportunity_display


def test_blocked_visible_approved_blocked_not_packageable_and_technical_change_preserves_review(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    service.approve(prospect.prospect_id)
    os.remove(concept.image_path)
    row = service.list_rows([prospect.prospect_id])[0]
    assert row.review_status == CAMPAIGN_REVIEW_STATUS_APPROVED
    assert row.technical_status == EXPORT_STATUS_BLOCKED
    assert row.packageable is False


def test_bulk_actions_filters_and_summary(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    ids = ["a", "b", "c", "d"]
    for prospect_id in ids:
        prospect = _prospect(prospect_store, prospect_id=prospect_id, company_name=f"{prospect_id.upper()} Co")
        if prospect_id == "d":
            continue
        project, concept = _project_with_concept(project_store, prospect, f"{prospect_id}.png")
        if prospect_id == "b":
            prospect.contact_name = ""
            prospect_store.save()
        _job(job_store, id=f"job-{prospect_id}", prospect_id=prospect_id, project_id=project.id, result_path=concept.image_path)
    service.bulk_approve(["a", "b"])
    service.bulk_exclude(["c"])
    service.bulk_mark_needs_review(["d"])
    rows = service.list_rows(ids)
    approved = service.filter_rows(rows, REVIEW_FILTER_APPROVED)
    excluded = service.filter_rows(rows, REVIEW_FILTER_EXCLUDED)
    needs_review = service.filter_rows(rows, REVIEW_FILTER_NEEDS_REVIEW)
    blocked = service.filter_rows(rows, REVIEW_FILTER_BLOCKED)
    summary = service.summary(ids)
    assert [row.prospect_id for row in approved] == ["a", "b"]
    assert [row.prospect_id for row in excluded] == ["c"]
    assert [row.prospect_id for row in needs_review if row.prospect_id == "d"] == ["d"]
    assert [row.prospect_id for row in blocked] == ["d"]
    assert summary.total == 4
    assert summary.approved == 2
    assert summary.excluded == 1
    assert summary.needs_review == 1
    assert summary.technically_blocked == 1
    assert summary.approved_packageable == 2


def test_read_only_and_build_approved_package_policy(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    ready = _prospect(prospect_store, prospect_id="ready", company_name="Ready Co")
    warning = _prospect(prospect_store, prospect_id="warning", company_name="Warn Co", contact_name="")
    excluded = _prospect(prospect_store, prospect_id="excluded", company_name="Excluded Co")
    blocked = _prospect(prospect_store, prospect_id="blocked", company_name="Blocked Co")
    for prospect in [ready, warning, excluded]:
        project, concept = _project_with_concept(project_store, prospect, f"{prospect.prospect_id}.png")
        _job(job_store, id=f"job-{prospect.prospect_id}", prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    before_jobs = [job.to_dict() for job in job_store.list()]
    before_projects = [project.id for project in project_store.list()]
    service.approve("ready")
    service.approve("warning")
    service.exclude("excluded")
    service.approve("blocked")
    rows = {row.prospect_id: row for row in service.list_rows(["ready", "warning", "excluded", "blocked"])}
    assert rows["ready"].technical_status == EXPORT_STATUS_READY
    assert rows["warning"].technical_status == EXPORT_STATUS_WARNING
    assert rows["blocked"].technical_status == EXPORT_STATUS_BLOCKED
    result = service.build_approved_package(["ready", "warning", "excluded", "blocked"], str(tmp_path / "packages"), "approved_only")
    assert result.success is True
    assert result.included_count == 2
    assert result.blocked_count == 0
    assert [job.to_dict() for job in job_store.list()] == before_jobs
    assert [project.id for project in project_store.list()] == before_projects


def test_mockup_preview_safe_when_missing(tmp_path):
    prospect_store, job_store, project_store, _, _, _, service = _runtime(tmp_path)
    prospect = _prospect(prospect_store)
    project, concept = _project_with_concept(project_store, prospect)
    _job(job_store, prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    os.remove(concept.image_path)
    row = service.list_rows([prospect.prospect_id])[0]
    assert row.mockup_path.endswith("mockup.png")
    assert row.technical_status == EXPORT_STATUS_BLOCKED


def test_friendly_status_formatting_examples() -> None:
    assert format_status("NEEDS_REVIEW") == "Needs review"
    assert "email address" in format_blocker("Missing email").lower()


def test_campaign_review_page_package_gating_messages() -> None:
    from PySide6.QtWidgets import QApplication

    from gui.views.campaign_review_page import CampaignReviewPage

    app = QApplication.instance() or QApplication([])
    page = CampaignReviewPage()
    page.set_controller(type("Controller", (), {"refresh": lambda self: None, "rows_changed": type("S", (), {"connect": lambda self, fn: None})(), "selection_changed": type("S", (), {"connect": lambda self, fn: None})(), "summary_changed": type("S", (), {"connect": lambda self, fn: None})(), "status_message": type("S", (), {"connect": lambda self, fn: None})(), "error_message": type("S", (), {"connect": lambda self, fn: None})(), "resolve_preferred_package_directory": lambda self: ""})())
    summary = type("Summary", (), {"approved_packageable": 0, "total": 0, "approved": 0, "excluded": 0, "needs_review": 0, "technically_blocked": 0})()
    page.set_summary(summary)
    assert page.build_package_button.isEnabled() is False
    assert "Approve at least one campaign-ready prospect" in page.build_package_button.toolTip()
    page._build_approved_package()
    assert "Approve at least one campaign-ready prospect" in page.message_label.text()
    assert app is not None


def test_campaign_review_right_pane_scrolls_and_actions_exist() -> None:
    from PySide6.QtWidgets import QApplication

    from gui.views.campaign_review_page import CampaignReviewPage

    app = QApplication.instance() or QApplication([])
    page = CampaignReviewPage()
    page.resize(1250, 800)
    page.show()
    app.processEvents()

    assert page.detail_scroll_area.widgetResizable() is True
    assert page.detail_scroll_area.widget() is page.detail_content
    assert page.approve_button is not None
    assert page.exclude_button is not None
    assert page.needs_review_button is not None
    assert page.save_note_button is not None
    assert page.open_project_button is not None
    assert page.open_mockup_button is not None
    assert page.open_folder_button is not None
    assert page.build_package_button is not None
    assert page.smartlead_button is not None
    assert page.open_existing_package_button is not None
    assert page.email_body.minimumHeight() > 0
    assert page.note_edit.minimumHeight() > 0
    assert app is not None