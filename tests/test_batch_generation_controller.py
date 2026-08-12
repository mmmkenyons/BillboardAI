from __future__ import annotations

import os
import time

import pytest

from gui.controllers.batch_generation_controller import BatchGenerationController
from gui.controllers.prospect_controller import ProspectController
from gui.models.mockup_result import MockupResult
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.prospect_generation import ProspectGenerationService
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.main_window import MainWindow
from gui.views.batch_page import BatchPage


def _qapplication():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        pytest.skip("PySide6 not available")
    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


def _wait_until(predicate, timeout_ms: int = 5000) -> None:
    app = _qapplication()
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
    app.processEvents()
    assert predicate(), "Timed out waiting for Qt condition"


def _setup(tmp_path, fake_generate=None):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    for prospect in [
        Prospect(prospect_id="a", company_name="A Co", website="https://a.com", category="roofing"),
        Prospect(prospect_id="b", company_name="B Co", website="https://b.com", category="unknown"),
        Prospect(prospect_id="c", company_name="C Co", website="https://c.com", category="dentist"),
    ]:
        prospect_store.create(prospect)
    prospect_store.save()
    service = ProspectWorkspaceService(store=prospect_store)
    prospect_controller = ProspectController(service=service)
    generation_service = ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json")),
        generation_callable=fake_generate or (lambda request: MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)),
        default_output_root=os.path.join(str(tmp_path), "projects"),
        project_store=ProjectStore(root=os.path.join(str(tmp_path), "projects")),
    )
    return prospect_store, prospect_controller, BatchGenerationController(prospect_controller=prospect_controller, service=generation_service)


def test_batch_page_constructs_and_populates(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    assert page.prospect_table.rowCount() == 3
    assert page.prospect_table.item(0, 1) is not None


def test_eligibility_renders_and_no_generation_on_open(tmp_path) -> None:
    _qapplication()
    calls = []

    def fake_generate(request):
        calls.append(request.url)
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    _, prospect_controller, batch_controller = _setup(tmp_path, fake_generate=fake_generate)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    assert "Ready" in page.prospect_table.item(0, 4).text()
    assert "No supported template" in page.prospect_table.item(1, 4).text()
    assert calls == []


def test_queue_selected_and_template_override(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, 0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    page.prospect_table.item(1, 0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    combo = page.prospect_table.cellWidget(1, 3)
    idx = combo.findData("contractor")
    combo.setCurrentIndex(idx)
    batch_controller.queue_selected(page.selected_prospect_ids(), page.selected_templates())
    assert page.jobs_table.rowCount() == 2


def test_stable_selection_uses_prospect_id(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    item = page.prospect_table.item(2, 0)
    item.setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    assert page.selected_prospect_ids() == [item.data(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemDataRole.UserRole)]


def test_run_queue_prevents_overlap_and_updates_status(tmp_path) -> None:
    _qapplication()
    outcomes = {"https://a.com": "success", "https://c.com": "fail"}

    def fake_generate(request):
        outcome = outcomes.get(request.url, "success")
        if outcome == "fail":
            raise RuntimeError("boom")
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    _, prospect_controller, batch_controller = _setup(tmp_path, fake_generate=fake_generate)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    for row in (0, 2):
        page.prospect_table.item(row, 0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    batch_controller.queue_selected(page.selected_prospect_ids(), page.selected_templates())
    batch_controller.run_queue()
    assert batch_controller.is_running is True
    batch_controller.run_queue()
    _wait_until(lambda: batch_controller.is_running is False)
    jobs = batch_controller._service.list_jobs()
    job_statuses = {job.prospect_id: job.status for job in jobs}
    assert job_statuses["a"] == "SUCCEEDED"
    assert job_statuses["c"] == "FAILED"
    statuses = [page.jobs_table.item(row, 2).text() for row in range(page.jobs_table.rowCount())]
    assert "SUCCEEDED" in statuses
    assert "FAILED" in statuses


def test_persisted_jobs_reappear_after_refresh(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.queue_selected(["a"], {})
    batch_controller.refresh()
    assert page.jobs_table.rowCount() == 1


def test_open_project_compatibility(tmp_path) -> None:
    _qapplication()

    def fake_generate(request):
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    prospect_store, prospect_controller, batch_controller = _setup(tmp_path, fake_generate=fake_generate)
    prospect_controller.load()
    batch_controller.queue_selected(["a"], {})
    opened = []
    batch_controller.open_project_requested.connect(lambda project_id: opened.append(project_id))
    batch_controller.run_queue()
    _wait_until(lambda: batch_controller.is_running is False)
    prospect = prospect_store.get("a")
    assert prospect is not None and prospect.metadata.get("project_id")
    batch_controller.open_project_for_prospect("a")
    assert opened
    assert batch_controller._service.project_store.exists(opened[0])


def test_main_window_prospect_only_wiring_does_not_call_batch_set_prospects_without_rows(tmp_path) -> None:
    _qapplication()
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    prospect_store.create(Prospect(prospect_id="only", company_name="Only Co", website="https://only.com", category="roofing"))
    prospect_store.save()
    service = ProspectWorkspaceService(store=prospect_store)
    controller = ProspectController(service=service)
    window = MainWindow(prospect_controller=controller)
    window.show_page("pipeline")
    assert window.batch_page.prospect_table.rowCount() == 0