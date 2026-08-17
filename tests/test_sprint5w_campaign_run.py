from __future__ import annotations

import os

from PySide6.QtCore import Qt

from gui.controllers.campaign_run_controller import CampaignRunController
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import (
    ACTION_BUILD_PACKAGE,
    ACTION_GENERATE,
    ACTION_RESEARCH,
    ACTION_REVIEW,
    ACTION_READY,
    RUN_STATE_IN_PROGRESS,
    RUN_STATE_NEEDS_ATTENTION,
    CampaignRunService,
)
from gui.views.campaign_run_page import CampaignRunPage
from gui.main_window import MainWindow


def _app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


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
    return prospect_store, job_store, project_store, review_service, run_service


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


def test_campaign_run_persists_scope_only_and_restores_after_restart(tmp_path):
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co")
    _prospect(prospect_store, prospect_id="b", company_name="B Co")
    run = run_service.create_run("Alpha", ["a", "b"], source="manual")

    reloaded = CampaignRunService(run_store=CampaignRunStore(path=run_service.run_store.path), prospect_store=prospect_store)
    restored = reloaded.get_run(run.id)
    assert restored is not None
    assert restored.id == run.id
    assert restored.prospect_ids == ["a", "b"]
    payload = open(run_service.run_store.path, "r", encoding="utf-8").read()
    assert "research_status" not in payload
    assert "review_status" not in payload
    assert "mockup_path" not in payload


def test_campaign_run_rows_derive_heterogeneous_golden_path_states(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service = _runtime(tmp_path)

    a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co", website="", email="b@example.com")
    c = _prospect(prospect_store, prospect_id="c", company_name="C Co", email="c@example.com")
    d = _prospect(prospect_store, prospect_id="d", company_name="D Co", email="d@example.com")
    e = _prospect(prospect_store, prospect_id="e", company_name="E Co", email="e@example.com")

    ap, ac = _project_with_concept(project_store, a, "a.png")
    cp, cc = _project_with_concept(project_store, c, "c.png")
    dp, dc = _project_with_concept(project_store, d, "d.png")
    ep, ec = _project_with_concept(project_store, e, "e.png")

    _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
    _job(job_store, id="job-c", prospect_id="c", project_id=cp.id, result_path=cc.image_path)
    _job(job_store, id="job-d", prospect_id="d", project_id=dp.id, result_path=dc.image_path)
    _job(job_store, id="job-e", prospect_id="e", project_id=ep.id, result_path=ec.image_path)

    review_service.approve("a")
    review_service.approve("e")

    package_result = review_service.build_approved_package(["a", "e"], str(tmp_path / "packages"), "alpha")
    assert package_result.success is True

    run = run_service.create_run("Run 1", ["a", "b", "c", "d", "e"])
    rows = {row.prospect_id: row for row in run_service.snapshot(run.id, package_directory=package_result.package_directory).rows}

    assert rows["a"].next_action in {ACTION_READY, "Prepare Smartlead", ACTION_BUILD_PACKAGE}
    assert rows["b"].next_action == ACTION_RESEARCH or rows["b"].next_action == "Add website"
    assert rows["c"].next_action == ACTION_REVIEW
    assert rows["d"].next_action == ACTION_REVIEW
    assert rows["e"].next_action in {ACTION_READY, "Prepare Smartlead", ACTION_BUILD_PACKAGE}


def test_continue_campaign_is_read_only_navigation(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    project, concept = _project_with_concept(project_store, prospect, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    review_service.approve("a")
    run = run_service.create_run("Read Only", ["a"])

    controller = CampaignRunController(service=run_service)
    controller.open_run(run.id)
    before_jobs = [job.to_dict() for job in job_store.list()]
    before_runs = open(run_service.run_store.path, "r", encoding="utf-8").read()
    target = controller.continue_campaign()
    after_jobs = [job.to_dict() for job in job_store.list()]
    after_runs = open(run_service.run_store.path, "r", encoding="utf-8").read()

    assert target in {"campaign_review", "smartlead", "campaign_run"}
    assert before_jobs == after_jobs
    assert before_runs == after_runs


def test_cross_run_isolation_and_scope_removal(tmp_path):
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    for pid in ("a", "b", "c", "d", "e"):
        _prospect(prospect_store, prospect_id=pid, company_name=f"{pid.upper()} Co")
    alpha = run_service.create_run("Alpha", ["a", "b", "c"])
    beta = run_service.create_run("Beta", ["d", "e"])

    run_service.remove_prospects(alpha.id, ["b"])
    assert run_service.get_run(alpha.id).prospect_ids == ["a", "c"]
    assert run_service.get_run(beta.id).prospect_ids == ["d", "e"]
    assert prospect_store.get("b") is not None


def test_run_summary_and_recommended_next_action(tmp_path):
    prospect_store, job_store, project_store, review_service, run_service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co", website="", email="b@example.com")
    project, concept = _project_with_concept(project_store, a, "a.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=project.id, result_path=concept.image_path)
    review_service.approve("a")
    run = run_service.create_run("Summary", ["a", "b"])
    summary = run_service.snapshot(run.id).summary

    assert summary.total_prospects == 2
    assert summary.generated >= 1
    assert summary.overall_state in {RUN_STATE_IN_PROGRESS, RUN_STATE_NEEDS_ATTENTION}
    assert summary.recommended_next_action in {ACTION_RESEARCH, "Add website", ACTION_BUILD_PACKAGE}


def test_campaign_run_page_constructs_and_binds_controller(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.create_run("UI Run", ["a"])
    controller.refresh()
    _app().processEvents()

    assert page.run_combo.count() >= 1
    assert page.table.columnCount() == 9
    assert page.continue_button.text() == "Continue Campaign"


def test_run_selector_is_non_editable_and_lists_existing_runs(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    alpha = run_service.create_run("Alpha", ["a"])
    beta = run_service.create_run("Beta", ["b"])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(alpha.id)
    _app().processEvents()

    assert page.run_combo.isEditable() is False
    labels = [page.run_combo.itemText(i) for i in range(page.run_combo.count())]
    assert "Alpha (1)" in labels
    assert "Beta (1)" in labels


def test_selecting_run_changes_current_run_and_new_run_becomes_selected(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    alpha = run_service.create_run("Alpha", ["a"])
    beta = run_service.create_run("Beta", ["b"])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(alpha.id)
    _app().processEvents()

    beta_index = page.run_combo.findData(beta.id)
    page.run_combo.setCurrentIndex(beta_index)
    _app().processEvents()
    assert controller.active_run_id() == beta.id

    new_run_id = controller.create_run("Gamma", ["a", "b"])
    _app().processEvents()
    assert controller.active_run_id() == new_run_id
    assert page.run_combo.currentData() == new_run_id


def test_populated_run_auto_selects_first_row_and_populates_detail(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)

    controller.open_run(run.id)
    _app().processEvents()

    assert controller.selected_prospect_id() == "a"
    assert page.current_prospect_id() == "a"
    assert page.detail_company.text() == "A Co"
    assert page.table.selectionBehavior() == page.table.SelectionBehavior.SelectRows


def test_empty_run_clears_selection_and_detail(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    populated = run_service.create_run("Populated", ["a"])
    empty = run_service.create_run("Empty", [])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(populated.id)
    _app().processEvents()

    controller.open_run(empty.id)
    _app().processEvents()

    assert controller.selected_prospect_id() is None
    assert page.current_prospect_id() == ""
    assert page.detail_company.text() == "—"


def test_clicking_another_row_updates_selection_and_detail(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(run.id)
    _app().processEvents()

    page.table.selectRow(1)
    _app().processEvents()

    assert controller.selected_prospect_id() == "b"
    assert page.current_prospect_id() == "b"
    assert page.detail_company.text() == "B Co"


def test_campaign_run_layout_contract_at_restored_size(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    run = run_service.create_run("Alpha", ["a"])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.resize(1280, 840)
    page.set_controller(controller)
    controller.open_run(run.id)
    page.show()
    _app().processEvents()

    assert page.splitter.orientation() == Qt.Orientation.Horizontal
    assert page.splitter.count() == 2
    left = page.splitter.widget(0)
    right = page.splitter.widget(1)
    assert left.width() > 0
    assert right.width() > 0
    assert left.geometry().right() <= right.geometry().left() + page.splitter.handleWidth()
    assert page.continue_button.width() > 0
    assert page.add_prospects_button.width() > 0
    assert left.minimumWidth() <= 320
    assert right.minimumWidth() <= 260


def test_campaign_run_uses_canonical_prospect_data_after_update(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    prospect = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    run = run_service.create_run("Alpha", ["a"])

    prospect.company_name = "A Co Updated"
    prospect.email = "updated@example.com"
    prospect_store.update(prospect)
    prospect_store.save()

    snapshot = run_service.snapshot(run.id)
    assert snapshot.run is not None
    assert snapshot.run.prospect_ids == ["a"]
    assert snapshot.rows[0].company_name == "A Co Updated"
    assert snapshot.rows[0].email == "updated@example.com"


def test_existing_run_survives_selector_refresh_and_restart(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])

    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(run.id)
    _app().processEvents()

    page.set_runs(controller.list_runs())
    _app().processEvents()

    assert run_service.get_run(run.id).prospect_ids == ["a", "b"]
    assert len(controller.last_snapshot().rows) == 2

    reloaded_run_store = CampaignRunStore(path=run_service.run_store.path)
    reloaded_service = CampaignRunService(
        run_store=reloaded_run_store,
        prospect_store=prospect_store,
        job_store=run_service._job_store,
        project_store=run_service._project_store,
        review_store=run_service._review_store,
        export_service=run_service.export_service,
        review_service=run_service.review_service,
    )
    reloaded = reloaded_service.snapshot(run.id)
    assert reloaded.run is not None
    assert reloaded.run.prospect_ids == ["a", "b"]
    assert len(reloaded.rows) == 2


def test_run_selector_reselection_does_not_mutate_membership(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    alpha = run_service.create_run("Alpha", ["a", "b"])
    beta = run_service.create_run("Beta", ["b"])
    before = [run.to_dict() for run in run_service.list_runs()]

    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(alpha.id)
    _app().processEvents()
    page.set_runs(controller.list_runs())
    beta_index = page.run_combo.findData(beta.id)
    alpha_index = page.run_combo.findData(alpha.id)
    page.run_combo.setCurrentIndex(beta_index)
    _app().processEvents()
    page.set_runs(controller.list_runs())
    page.run_combo.setCurrentIndex(alpha_index)
    _app().processEvents()

    after = [run.to_dict() for run in run_service.list_runs()]
    assert before == after
    assert run_service.get_run(alpha.id).prospect_ids == ["a", "b"]


def test_add_prospects_enabled_for_selected_empty_run_when_prospects_exist(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    empty = run_service.create_run("Empty", [])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)

    controller.open_run(empty.id)
    _app().processEvents()

    assert controller.active_run_id() == empty.id
    assert page.add_prospects_button.isEnabled() is True


def test_snapshot_loads_canonical_store_before_resolving_rows(tmp_path):
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])

    cold_prospect_store = ProspectStore(path=prospect_store.path)
    cold_run_service = CampaignRunService(
        run_store=CampaignRunStore(path=run_service.run_store.path),
        prospect_store=cold_prospect_store,
        job_store=run_service._job_store,
        project_store=run_service._project_store,
        review_store=run_service._review_store,
        export_service=run_service.export_service,
        review_service=run_service.review_service,
    )

    snapshot = cold_run_service.snapshot(run.id)
    assert len(snapshot.rows) == 2
    assert snapshot.rows[0].company_name == "A Co"
    assert snapshot.rows[1].company_name == "B Co"


def test_initial_selection_does_not_scroll_table_horizontally(tmp_path):
    _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="verylongemailaddress_a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="verylongemailaddress_b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])
    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.resize(1280, 840)
    page.set_controller(controller)
    page.show()

    controller.open_run(run.id)
    _app().processEvents()

    scrollbar = page.table.horizontalScrollBar()
    assert scrollbar.value() == scrollbar.minimum() == 0
    page.table.selectRow(0)
    _app().processEvents()
    assert scrollbar.value() == 0


def test_hosted_mainwindow_initial_campaign_run_selection_syncs_active_run(tmp_path):
    app = _app()
    prospect_store, job_store, project_store, _review_service, run_service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    run = run_service.create_run("Alpha", [a.prospect_id, b.prospect_id])

    controller = CampaignRunController(service=run_service)
    window = MainWindow(campaign_run_controller=controller)
    page = window.campaign_run_page
    window.show_page("campaign_run")
    app.processEvents()

    observed = {
        "combo_current_data": page.run_combo.currentData(),
        "combo_current_text": page.run_combo.currentText(),
        "controller_active_run_id": controller.active_run_id(),
        "snapshot_total": controller.last_snapshot().summary.total_prospects if controller.last_snapshot() else None,
        "snapshot_rows": len(controller.last_snapshot().rows) if controller.last_snapshot() else None,
        "table_row_count": page.table.rowCount(),
        "summary_label": page.summary_label.text(),
        "add_prospects_enabled": page.add_prospects_button.isEnabled(),
    }

    assert observed["combo_current_data"] == run.id, observed
    assert controller.active_run_id() == run.id, observed
    assert observed["snapshot_total"] == 2, observed
    assert observed["snapshot_rows"] == 2, observed
    assert observed["table_row_count"] == 2, observed
    assert observed["add_prospects_enabled"] is True, observed


def test_campaign_run_repopulation_preserves_active_run_and_membership(tmp_path):
    app = _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    alpha = run_service.create_run("Alpha", ["a", "b"])
    beta = run_service.create_run("Beta", ["b"])

    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.set_controller(controller)
    controller.open_run(alpha.id)
    app.processEvents()

    before = [run.to_dict() for run in run_service.list_runs()]
    page.set_runs(controller.list_runs())
    app.processEvents()
    assert controller.active_run_id() == alpha.id
    assert page.run_combo.currentData() == alpha.id
    assert page.table.rowCount() == 2

    beta_index = page.run_combo.findData(beta.id)
    page.run_combo.setCurrentIndex(beta_index)
    app.processEvents()
    assert controller.active_run_id() == beta.id
    assert page.table.rowCount() == 1

    page.set_runs(controller.list_runs())
    app.processEvents()
    assert controller.active_run_id() == beta.id
    assert page.run_combo.currentData() == beta.id
    assert page.table.rowCount() == 1

    alpha_index = page.run_combo.findData(alpha.id)
    page.run_combo.setCurrentIndex(alpha_index)
    app.processEvents()
    assert controller.active_run_id() == alpha.id
    assert page.table.rowCount() == 2
    assert [run.to_dict() for run in run_service.list_runs()] == before


def test_campaign_run_company_column_starts_inside_viewport_at_restored_width(tmp_path):
    app = _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="verylongemailaddress_a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="verylongemailaddress_b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])

    controller = CampaignRunController(service=run_service)
    page = CampaignRunPage()
    page.resize(1280, 840)
    page.set_controller(controller)
    controller.open_run(run.id)
    app.processEvents()

    header = page.table.horizontalHeader()
    scrollbar = page.table.horizontalScrollBar()
    before = {
        "scrollbar_value": scrollbar.value(),
        "scrollbar_min": scrollbar.minimum(),
        "header_offset": header.offset(),
        "section_viewport_position": header.sectionViewportPosition(page.COL_COMPANY),
        "column_viewport_position": page.table.columnViewportPosition(page.COL_COMPANY),
        "vertical_header_visible": page.table.verticalHeader().isVisible(),
        "vertical_header_width": page.table.verticalHeader().width(),
        "viewport_x": page.table.viewport().x(),
    }
    assert before["scrollbar_value"] == before["scrollbar_min"], before
    assert before["header_offset"] == 0, before
    assert before["section_viewport_position"] >= 0, before
    assert before["column_viewport_position"] >= 0, before

    page.table.selectRow(0)
    app.processEvents()
    after = {
        "scrollbar_value": scrollbar.value(),
        "header_offset": header.offset(),
        "section_viewport_position": header.sectionViewportPosition(page.COL_COMPANY),
        "column_viewport_position": page.table.columnViewportPosition(page.COL_COMPANY),
    }
    assert after["scrollbar_value"] == scrollbar.minimum(), after
    assert after["header_offset"] == 0, after
    assert after["section_viewport_position"] >= 0, after
    assert after["column_viewport_position"] >= 0, after


def test_hosted_mainwindow_campaign_run_geometry_starts_at_left_edge(tmp_path):
    app = _app()
    prospect_store, _job_store, _project_store, _review_service, run_service = _runtime(tmp_path)
    _prospect(prospect_store, prospect_id="a", company_name="A Co", email="verylongemailaddress_a@example.com")
    _prospect(prospect_store, prospect_id="b", company_name="B Co", email="verylongemailaddress_b@example.com")
    run = run_service.create_run("Alpha", ["a", "b"])

    controller = CampaignRunController(service=run_service)
    window = MainWindow(campaign_run_controller=controller)
    page = window.campaign_run_page
    window.resize(1280, 840)
    window.show_page("campaign_run")
    app.processEvents()

    assert page.run_combo.currentData() == run.id
    assert controller.active_run_id() == run.id

    header = page.table.horizontalHeader()
    scrollbar = page.table.horizontalScrollBar()

    before = {
        "scrollbar_value": scrollbar.value(),
        "scrollbar_min": scrollbar.minimum(),
        "header_offset": header.offset(),
        "section_viewport_position": header.sectionViewportPosition(page.COL_COMPANY),
        "column_viewport_position": page.table.columnViewportPosition(page.COL_COMPANY),
        "vertical_header_visible": page.table.verticalHeader().isVisible(),
        "vertical_header_width": page.table.verticalHeader().width(),
        "viewport_x": page.table.viewport().x(),
    }
    assert before["scrollbar_value"] == before["scrollbar_min"], before
    assert before["header_offset"] == 0, before
    assert before["section_viewport_position"] >= 0, before
    assert before["column_viewport_position"] >= 0, before

    page.table.selectRow(0)
    app.processEvents()
    after = {
        "scrollbar_value": scrollbar.value(),
        "header_offset": header.offset(),
        "section_viewport_position": header.sectionViewportPosition(page.COL_COMPANY),
        "column_viewport_position": page.table.columnViewportPosition(page.COL_COMPANY),
    }
    assert after["scrollbar_value"] == scrollbar.minimum(), after
    assert after["header_offset"] == 0, after
    assert after["section_viewport_position"] >= 0, after
    assert after["column_viewport_position"] >= 0, after


def test_campaign_run_layout_contract_at_restored_size(tmp_path):
    app = _app()
    prospect_store, job_store, project_store, review_service, run_service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="T2 Roofing", email="verylongemailaddress_a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="Bobs burgers", email="verylongemailaddress_b@example.com")
    ap, ac = _project_with_concept(project_store, a, "a.png")
    bp, bc = _project_with_concept(project_store, b, "b.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
    _job(job_store, id="job-b", prospect_id="b", project_id=bp.id, result_path=bc.image_path)
    review_service.approve("a")
    review_service.approve("b")
    run = run_service.create_run("Alpha", ["a", "b"])

    controller = CampaignRunController(service=run_service)
    window = MainWindow(campaign_run_controller=controller)
    page = window.campaign_run_page
    window.resize(1280, 840)
    window.show_page("campaign_run")
    app.processEvents()

    assert page.run_combo.currentData() == run.id
    assert controller.active_run_id() == run.id
    assert page.table.verticalHeader().isHidden()

    header = page.table.horizontalHeader()
    scrollbar = page.table.horizontalScrollBar()
    item_rect = page.table.visualItemRect(page.table.item(0, page.COL_COMPANY))

    assert scrollbar.value() == scrollbar.minimum()
    assert header.offset() == 0
    assert header.sectionViewportPosition(page.COL_COMPANY) >= 0
    assert page.table.columnViewportPosition(page.COL_COMPANY) >= 0
    assert item_rect.x() >= 0
    assert page.table.viewport().x() == page.table.frameWidth()
    assert page.splitter.widget(1).width() > 0


def test_campaign_run_company_column_stays_visible_when_host_maximized(tmp_path):
    app = _app()
    prospect_store, job_store, project_store, review_service, run_service = _runtime(tmp_path)
    a = _prospect(prospect_store, prospect_id="a", company_name="T2 Roofing", email="verylongemailaddress_a@example.com")
    b = _prospect(prospect_store, prospect_id="b", company_name="Bobs burgers", email="verylongemailaddress_b@example.com")
    ap, ac = _project_with_concept(project_store, a, "a.png")
    bp, bc = _project_with_concept(project_store, b, "b.png")
    _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
    _job(job_store, id="job-b", prospect_id="b", project_id=bp.id, result_path=bc.image_path)
    review_service.approve("a")
    review_service.approve("b")
    run = run_service.create_run("Alpha", ["a", "b"])

    controller = CampaignRunController(service=run_service)
    window = MainWindow(campaign_run_controller=controller)
    page = window.campaign_run_page
    window.show_page("campaign_run")
    window.showMaximized()
    app.processEvents()

    assert page.run_combo.currentData() == run.id
    assert controller.active_run_id() == run.id
    assert page.table.verticalHeader().isHidden()

    header = page.table.horizontalHeader()
    scrollbar = page.table.horizontalScrollBar()
    item_rect = page.table.visualItemRect(page.table.item(0, page.COL_COMPANY))

    assert scrollbar.value() == scrollbar.minimum()
    assert header.offset() == 0
    assert header.sectionViewportPosition(page.COL_COMPANY) >= 0
    assert page.table.columnViewportPosition(page.COL_COMPANY) >= 0
    assert item_rect.x() >= 0
    assert page.splitter.widget(1).width() > 0