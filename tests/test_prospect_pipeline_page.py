"""Sprint 5I Prospect Pipeline page/controller tests."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.controllers.prospect_controller import ProspectController
from gui.main_window import MainWindow
from gui.models.prospect import (
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    WORKFLOW_STATUS_FOLLOW_UP,
    WORKFLOW_STATUS_NEW,
    WORKFLOW_STATUS_WON,
)
from gui.models.prospect_store import ProspectStore
from gui.services.prospect_workspace import ProspectWorkspaceService


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _seed_controller(tmp_path):
    path = os.path.join(str(tmp_path), "prospects.json")
    controller = ProspectController(path=path)
    svc = controller.service
    svc.load()
    alpha = svc.create_prospect(company_name="Alpha Co", website="alpha.com")
    beta = svc.create_prospect(company_name="Beta Co", website="beta.com")
    svc.update_workflow(alpha.prospect_id, status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action="Call Alpha", next_action_date="2026-08-14")
    svc.update_workflow(beta.prospect_id, status=WORKFLOW_STATUS_NEW, priority=PRIORITY_NORMAL, next_action="Email Beta", next_action_date="2026-08-20")
    controller.reload()
    return controller, alpha.prospect_id, beta.prospect_id


class TestPipelinePage:
    def test_page_constructs_safely(self, tmp_path) -> None:
        _ensure_qapp()
        from gui.views.prospect_pipeline_page import ProspectPipelinePage
        page = ProspectPipelinePage()
        assert page is not None

    def test_empty_store_renders_safely(self, tmp_path) -> None:
        _ensure_qapp()
        from gui.views.prospect_pipeline_page import ProspectPipelinePage
        controller = ProspectController(path=os.path.join(str(tmp_path), "prospects.json"))
        page = ProspectPipelinePage()
        page.set_controller(controller)
        assert page.stage_table.rowCount() > 0
        assert page.prospect_table.rowCount() == 0

    def test_summary_and_stage_counts_populate(self, tmp_path) -> None:
        _ensure_qapp()
        from gui.views.prospect_pipeline_page import ProspectPipelinePage
        controller, _, _ = _seed_controller(tmp_path)
        page = ProspectPipelinePage()
        page.set_controller(controller)
        assert page.summary_cards["total"].text() == "2"
        assert page.summary_cards["active"].text() == "2"
        counts = {page.stage_table.item(row, 0).data(Qt.ItemDataRole.UserRole): page.stage_table.item(row, 1).text() for row in range(page.stage_table.rowCount())}
        assert counts[WORKFLOW_STATUS_FOLLOW_UP] == "1"
        assert counts[WORKFLOW_STATUS_NEW] == "1"

    def test_selecting_stage_renders_correct_prospects_and_selection(self, tmp_path) -> None:
        _ensure_qapp()
        from gui.views.prospect_pipeline_page import ProspectPipelinePage
        controller, alpha_id, _ = _seed_controller(tmp_path)
        page = ProspectPipelinePage()
        page.set_controller(controller)
        for row in range(page.stage_table.rowCount()):
            item = page.stage_table.item(row, 0)
            if item.data(Qt.ItemDataRole.UserRole) == WORKFLOW_STATUS_FOLLOW_UP:
                page.stage_table.selectRow(row)
                break
        assert page.prospect_table.rowCount() == 1
        page.prospect_table.selectRow(0)
        assert page.selected_prospect_id() == alpha_id

    def test_open_prospect_routes_correctly_and_workspace_populates(self, tmp_path) -> None:
        _ensure_qapp()
        controller, alpha_id, _ = _seed_controller(tmp_path)
        window = MainWindow(prospect_controller=controller)
        window.show_page("pipeline")
        page = window.pipeline_page
        for row in range(page.stage_table.rowCount()):
            item = page.stage_table.item(row, 0)
            if item.data(Qt.ItemDataRole.UserRole) == WORKFLOW_STATUS_FOLLOW_UP:
                page.stage_table.selectRow(row)
                break
        page.prospect_table.selectRow(0)
        page._open_selected_prospect()
        assert window._stack.currentWidget() is window.prospects_workspace
        assert window.prospects_workspace.get_selected_prospect_id() == alpha_id
        selected = controller.get_selected()
        assert selected is not None
        assert selected.workflow_status == WORKFLOW_STATUS_FOLLOW_UP
        assert controller.snapshot is not None

    def test_workflow_update_refreshes_pipeline_counts(self, tmp_path) -> None:
        _ensure_qapp()
        controller, alpha_id, _ = _seed_controller(tmp_path)
        window = MainWindow(prospect_controller=controller)
        window.show_page("pipeline")
        assert window.pipeline_page.summary_cards["won"].text() == "0"
        controller.update_workflow(alpha_id, status=WORKFLOW_STATUS_WON, priority=PRIORITY_NORMAL)
        window.pipeline_page.refresh()
        assert window.pipeline_page.summary_cards["won"].text() == "1"

    def test_injected_store_remains_authoritative_and_no_side_effects(self, tmp_path) -> None:
        _ensure_qapp()
        path = os.path.join(str(tmp_path), "custom.json")
        service = ProspectWorkspaceService(store=ProspectStore(path=path))
        service.load()
        prospect = service.create_prospect(company_name="Injected Co", website="inj.com")
        service.update_workflow(prospect.prospect_id, status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action_date="2026-08-14")
        controller = ProspectController(service=service)
        window = MainWindow(prospect_controller=controller)
        window.show_page("pipeline")
        assert window.pipeline_page.summary_cards["total"].text() == "1"
        assert controller.snapshot is None

    def test_missing_backing_file_preserves_injected_in_memory_prospects(self, tmp_path) -> None:
        _ensure_qapp()
        path = os.path.join(str(tmp_path), "missing.json")
        store = ProspectStore(path=path)
        store.create(__import__("gui.models.prospect", fromlist=["Prospect"]).Prospect(
            prospect_id="mem_only",
            company_name="Memory Only",
            workflow_status=WORKFLOW_STATUS_FOLLOW_UP,
            priority=PRIORITY_HIGH,
            next_action_date="2026-08-14",
        ))
        service = ProspectWorkspaceService(store=store)
        controller = ProspectController(service=service)
        window = MainWindow(prospect_controller=controller)
        window.show_page("pipeline")
        assert window.pipeline_page.summary_cards["total"].text() == "1"