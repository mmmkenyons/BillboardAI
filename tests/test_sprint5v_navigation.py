from __future__ import annotations

import os

import pytest

from gui.controllers.campaign_review_controller import CampaignReviewController
from gui.main_window import MainWindow
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.controllers.prospect_controller import ProspectController
from gui.models.workflow_stage import WorkflowStageId
from gui.models.workflow_stage import WorkflowStageState
from gui.models.workflow_stage import WorkflowStageViewModel
from gui.widgets.workflow_bar import WorkflowBar


def _app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


def test_workflow_navigation_is_read_only(tmp_path):
    _app()
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    service = ProspectWorkspaceService(store=store)
    controller = ProspectController(service=service)
    controller.create_prospect(company_name="A Co", website="a.com")
    store.save()
    before = open(store.path, "r", encoding="utf-8").read()
    window = MainWindow(prospect_controller=controller)
    window.show_page("prospects")
    window.show_page("pipeline")
    window.show_page("prospects")
    after = open(store.path, "r", encoding="utf-8").read()
    assert before == after


def test_repeated_navigation_is_idempotent(tmp_path):
    _app()
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    service = ProspectWorkspaceService(store=store)
    controller = ProspectController(service=service)
    window = MainWindow(prospect_controller=controller)
    for _ in range(3):
        window.show_page("prospects")
        window.show_page("pipeline")
    assert window.workflow_bar is not None


def test_campaign_review_auto_handoff_uses_correct_package(tmp_path, monkeypatch):
    _app()
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    package_service = CampaignPackageService(export_service=export_service)
    review_store = CampaignReviewStore(path=os.path.join(str(tmp_path), "campaign_review.json"))
    review_service = CampaignReviewService(
        prospect_store=prospect_store,
        export_service=export_service,
        review_store=review_store,
        package_service=package_service,
    )
    controller = CampaignReviewController(service=review_service)
    called = []
    monkeypatch.setattr(controller, "prepare_smartlead_handoff", lambda directory: called.append(directory))
    monkeypatch.setattr(controller, "resolve_preferred_package_directory", lambda: "D:/package-a")
    from gui.views.campaign_review_page import CampaignReviewPage

    page = CampaignReviewPage()
    page.set_controller(controller)
    page._prepare_smartlead_handoff()
    assert called == ["D:/package-a"]


def test_package_context_a_b_isolation(monkeypatch, tmp_path):
    _app()
    from gui.views.campaign_review_page import CampaignReviewPage

    class StubController:
        def __init__(self, directory):
            self._directory = directory
            self.rows_changed = type("S", (), {"connect": lambda self, fn: None})()
            self.selection_changed = type("S", (), {"connect": lambda self, fn: None})()
            self.summary_changed = type("S", (), {"connect": lambda self, fn: None})()
            self.status_message = type("S", (), {"connect": lambda self, fn: None})()
            self.error_message = type("S", (), {"connect": lambda self, fn: None})()
            self.calls = []

        def resolve_preferred_package_directory(self):
            return self._directory

        def prepare_smartlead_handoff(self, directory):
            self.calls.append(directory)

        def refresh(self):
            return None

    controller_a = StubController("D:/package-a")
    controller_b = StubController("D:/package-b")
    page_a = CampaignReviewPage()
    page_b = CampaignReviewPage()
    page_a.set_controller(controller_a)
    page_b.set_controller(controller_b)
    page_a._prepare_smartlead_handoff()
    page_b._prepare_smartlead_handoff()
    assert controller_a.calls == ["D:/package-a"]
    assert controller_b.calls == ["D:/package-b"]


def test_review_scope_change_invalidates_stale_package_context(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    package_service = CampaignPackageService(export_service=export_service)
    review_store = CampaignReviewStore(path=os.path.join(str(tmp_path), "campaign_review.json"))
    review_service = CampaignReviewService(
        prospect_store=prospect_store,
        export_service=export_service,
        review_store=review_store,
        package_service=package_service,
    )
    controller = CampaignReviewController(service=review_service)
    controller.set_scope(["a"])
    controller._last_package_result = type("Result", (), {"success": True, "package_directory": "D:/package-a"})()
    assert controller.resolve_preferred_package_directory() == ""
    controller.set_scope(["b"])
    assert controller.resolve_preferred_package_directory() == ""


def test_main_window_has_no_settings_view_action(tmp_path):
    _app()
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    service = ProspectWorkspaceService(store=store)
    controller = ProspectController(service=service)
    window = MainWindow(prospect_controller=controller)
    view_action = next((action for action in window.menuBar().actions() if action.text() == "&View"), None)
    assert view_action is not None
    assert all("Settings" not in action.text() for action in view_action.menu().actions())


def test_workflow_bar_repeated_updates_and_single_click_signal():
    app = _app()
    bar = WorkflowBar()
    emitted = []
    bar.stage_requested.connect(emitted.append)

    first = [
        WorkflowStageViewModel(WorkflowStageId.PROSPECTS, "Prospects", "d", WorkflowStageState.READY, True),
        WorkflowStageViewModel(WorkflowStageId.RESEARCH, "Research", "d", WorkflowStageState.NOT_STARTED, False),
    ]
    second = [
        WorkflowStageViewModel(WorkflowStageId.PROSPECTS, "Prospects", "d", WorkflowStageState.COMPLETE, False),
        WorkflowStageViewModel(WorkflowStageId.RESEARCH, "Research", "d", WorkflowStageState.IN_PROGRESS, True),
        WorkflowStageViewModel(WorkflowStageId.OPPORTUNITIES, "Opportunities", "d", WorkflowStageState.READY, False),
    ]

    for _ in range(3):
        bar.set_stages(first)
        app.processEvents()
        assert bar.layout() is not None
        assert bar.layout().count() == 2
        bar.set_stages(second)
        app.processEvents()
        assert bar.layout() is not None
        assert bar.layout().count() == 3

    button = list(bar._buttons.values())[0]
    button.click()
    app.processEvents()
    assert emitted == [WorkflowStageId.PROSPECTS.value]


def test_main_window_refresh_workflow_bar_repeatedly(tmp_path):
    _app()
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    service = ProspectWorkspaceService(store=store)
    controller = ProspectController(service=service)
    controller.create_prospect(company_name="A Co", website="a.com")
    store.save()
    window = MainWindow(prospect_controller=controller)
    for _ in range(5):
        window._refresh_workflow_bar()
        _app().processEvents()
    assert window.workflow_bar.layout() is not None


def test_generate_stage_routes_to_batch(tmp_path):
    _app()
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    service = ProspectWorkspaceService(store=store)
    controller = ProspectController(service=service)
    window = MainWindow(prospect_controller=controller)
    window._on_workflow_stage_requested(WorkflowStageId.GENERATE.value)
    assert window._stack.currentWidget() is window.batch_page


def test_launch_stage_routes_to_smartlead_idempotently_without_writes(tmp_path):
    _app()
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    service = ProspectWorkspaceService(store=store)
    controller = ProspectController(service=service)
    window = MainWindow(prospect_controller=controller)
    before = open(store.path, "r", encoding="utf-8").read() if os.path.exists(store.path) else ""
    window._on_workflow_stage_requested(WorkflowStageId.LAUNCH.value)
    first = window._stack.currentWidget()
    window._on_workflow_stage_requested(WorkflowStageId.LAUNCH.value)
    second = window._stack.currentWidget()
    after = open(store.path, "r", encoding="utf-8").read() if os.path.exists(store.path) else ""
    assert first is window.smartlead_page
    assert second is window.smartlead_page
    assert before == after
