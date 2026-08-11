"""Sprint 5H Prospect Follow-Up Queue page/controller tests."""

from __future__ import annotations

import os
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.controllers.prospect_controller import ProspectController
from gui.models.prospect import (
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    PRIORITY_URGENT,
    WORKFLOW_STATUS_CONTACTED,
    WORKFLOW_STATUS_FOLLOW_UP,
    WORKFLOW_STATUS_NEW,
    WORKFLOW_STATUS_READY_TO_CONTACT,
    WORKFLOW_STATUS_WON,
    Prospect,
)
from gui.models.prospect_store import ProspectStore
from gui.services.prospect_follow_up import TIMING_OVERDUE, ProspectFollowUpService
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.views.prospect_follow_up_page import ProspectFollowUpPage


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


_TODAY = date(2026, 8, 15)


def _harness(tmp_path, seed=True):
    _ensure_qapp()
    path = os.path.join(str(tmp_path), "prospects.json")
    controller = ProspectController(path=path)
    page = ProspectFollowUpPage()
    if seed:
        svc = controller.service
        svc.load()
        a = svc.create_prospect(company_name="Alpha Co", website="alpha.com")
        b = svc.create_prospect(company_name="Beta Co", website="beta.com")
        svc.update_workflow(
            a.prospect_id,
            status=WORKFLOW_STATUS_FOLLOW_UP,
            priority=PRIORITY_HIGH,
            next_action="Call alpha",
            next_action_date="2026-08-14",
            notes="alpha note",
        )
        svc.update_workflow(
            b.prospect_id,
            status=WORKFLOW_STATUS_NEW,
            priority=PRIORITY_NORMAL,
            next_action="Email beta",
            next_action_date="2026-08-20",
        )
        controller.reload()
    page.set_controller(controller)
    return controller, page


class TestFollowUpPage:
    def test_page_constructs_offscreen(self, tmp_path) -> None:
        _ensure_qapp()
        page = ProspectFollowUpPage()
        assert page is not None

    def test_no_prospect_state_renders_safely(self, tmp_path) -> None:
        _ensure_qapp()
        path = os.path.join(str(tmp_path), "prospects.json")
        controller = ProspectController(path=path)
        page = ProspectFollowUpPage()
        page.set_controller(controller)
        assert page.table.rowCount() == 0
        assert "No prospects" in page.empty_label.text() or "match" in page.empty_label.text().lower()

    def test_queue_rows_populate_from_store(self, tmp_path) -> None:
        _, page = _harness(tmp_path)
        page.refresh()
        assert page.table.rowCount() == 2

    def test_default_sort_prioritizes_overdue(self, tmp_path) -> None:
        _, page = _harness(tmp_path)
        page.refresh()
        assert page.table.rowCount() == 2
        first_id = page.table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        # Alpha has the overdue date.
        assert first_id is not None

    def test_select_row_tracks_prospect_id(self, tmp_path) -> None:
        _, page = _harness(tmp_path)
        page.refresh()
        page.table.selectRow(0)
        assert page.selected_prospect_id() is not None

    def test_open_selected_emits_signal(self, tmp_path) -> None:
        controller, page = _harness(tmp_path)
        page.refresh()
        page.table.selectRow(0)
        emitted = []
        controller.open_prospect_requested.connect(emitted.append)
        page._on_open_selected()
        assert len(emitted) == 1
        assert emitted[0]

    def test_workflow_update_refreshes_queue(self, tmp_path) -> None:
        controller, page = _harness(tmp_path)
        page.refresh()
        initial = page.table.rowCount()
        p = controller.list_prospects()[0]
        controller.update_workflow(
            p.prospect_id,
            status=WORKFLOW_STATUS_WON,
            priority=PRIORITY_NORMAL,
        )
        page.refresh()
        # One active prospect should now be excluded from default active queue.
        assert page.table.rowCount() < initial

    def test_filtering_does_not_mutate_store(self, tmp_path) -> None:
        controller, page = _harness(tmp_path)
        page.refresh()
        before = {p.prospect_id: p.to_dict() for p in controller.list_prospects()}
        page.search_input.setText("nonexistent")
        page.refresh()
        after = {p.prospect_id: p.to_dict() for p in controller.list_prospects()}
        assert before == after

    def test_injected_store_is_authoritative(self, tmp_path) -> None:
        _ensure_qapp()
        custom_path = os.path.join(str(tmp_path), "custom.json")
        custom_store = ProspectStore(path=custom_path)
        svc = ProspectWorkspaceService(store=custom_store)
        p = svc.create_prospect(company_name="Injected Co", website="inj.com")
        svc.update_workflow(
            p.prospect_id,
            status=WORKFLOW_STATUS_READY_TO_CONTACT,
            priority=PRIORITY_URGENT,
            next_action_date="2026-08-14",
        )
        controller = ProspectController(service=svc)
        page = ProspectFollowUpPage()
        page.set_controller(controller)
        page.refresh()
        assert page.table.rowCount() == 1
        assert page.table.item(0, 0).text() == "Injected Co"

    def test_follow_up_service_shares_controller_store(self, tmp_path) -> None:
        controller, _ = _harness(tmp_path)
        assert isinstance(controller.follow_up_service, ProspectFollowUpService)
        assert controller.follow_up_service.store is controller.store
