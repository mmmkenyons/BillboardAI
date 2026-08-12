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
from gui.services.campaign_export import EXPORT_STATUS_BLOCKED
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
    assert page.prospect_table.item(0, BatchPage.COL_COMPANY) is not None


def test_eligibility_renders_and_no_generation_on_open(tmp_path) -> None:
    _qapplication()
    calls = []

    def fake_generate(request):
        calls.append(request.url)
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    _, prospect_controller, batch_controller = _setup(tmp_path, fake_generate=fake_generate)
    exportable = batch_controller._service.prospect_store.get("a")
    assert exportable is not None
    exportable.email = "owner@a.com"
    batch_controller._service.prospect_store.save()
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    assert "Ready" in page.prospect_table.item(0, BatchPage.COL_ELIGIBILITY).text()
    assert "No supported template" in page.prospect_table.item(1, BatchPage.COL_ELIGIBILITY).text()
    assert page.prospect_table.item(0, BatchPage.COL_OPPORTUNITY).text() in {"Generic", "No opportunity"}
    assert calls == []


def test_queue_selected_and_template_override(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    row_by_prospect_id = {}
    for row in range(page.prospect_table.rowCount()):
        item = page.prospect_table.item(row, BatchPage.COL_SELECT)
        assert item is not None
        prospect_id = item.data(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemDataRole.UserRole)
        row_by_prospect_id[str(prospect_id)] = row

    row_a = row_by_prospect_id["a"]
    row_b = row_by_prospect_id["b"]

    combo_a = page.prospect_table.cellWidget(row_a, BatchPage.COL_TEMPLATE)
    combo_b = page.prospect_table.cellWidget(row_b, BatchPage.COL_TEMPLATE)
    assert combo_a is not None
    assert combo_b is not None

    idx_a = combo_a.findData("contractor")
    idx_b = combo_b.findData("contractor")
    assert idx_a >= 0
    assert idx_b >= 0
    combo_a.setCurrentIndex(idx_a)
    combo_b.setCurrentIndex(idx_b)

    item_a = page.prospect_table.item(row_a, BatchPage.COL_SELECT)
    item_b = page.prospect_table.item(row_b, BatchPage.COL_SELECT)
    assert item_a is not None
    assert item_b is not None
    item_a.setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    item_b.setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)

    assert page.selected_prospect_ids() == ["a", "b"]
    assert page.selected_templates() == {"a": "contractor", "b": "contractor"}

    page.queue_button.click()
    assert page.jobs_table.rowCount() == 2
    jobs = batch_controller._service.list_jobs()
    assert [job.prospect_id for job in jobs] == ["a", "b"]
    templates_by_prospect = {job.prospect_id: job.template for job in jobs}
    assert templates_by_prospect["a"] == "contractor"
    assert templates_by_prospect["b"] == "contractor"


def test_stable_selection_uses_prospect_id(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    item = page.prospect_table.item(0, BatchPage.COL_SELECT)
    assert item is not None
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
    exportable = batch_controller._service.prospect_store.get("a")
    assert exportable is not None
    exportable.email = "owner@a.com"
    batch_controller._service.prospect_store.save()
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    for row in (0, 2):
        page.prospect_table.item(row, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    batch_controller.queue_selected(page.selected_prospect_ids(), page.selected_templates())
    batch_controller.run_queue()
    assert batch_controller.is_running is True
    batch_controller.run_queue()
    _wait_until(lambda: batch_controller.is_running is False)
    jobs = batch_controller._service.list_jobs()
    job_statuses = {job.prospect_id: job.status for job in jobs}
    assert job_statuses["a"] == "SUCCEEDED"
    assert job_statuses["c"] == "FAILED"
    statuses = [page.jobs_table.item(row, BatchPage.JOB_COL_STATUS).text() for row in range(page.jobs_table.rowCount())]
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


def test_set_controller_same_controller_is_idempotent(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    page.queue_button.click()
    jobs = batch_controller._service.list_jobs()
    assert len(jobs) == 1
    assert page.jobs_table.rowCount() == 1


def test_selection_survives_refresh(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    assert page.selected_prospect_ids() == ["a"]
    page.set_prospects([
        {"prospect_id": "a", "company_name": "A Co Updated", "website": "https://a.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Ready", "export_status": "Ready"},
        {"prospect_id": "b", "company_name": "B Co Updated", "website": "https://b.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Blocked", "export_status": "Blocked"},
    ])
    assert page.selected_prospect_ids() == ["a"]


def test_selection_follows_id_not_row_position(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    page.set_prospects([
        {"prospect_id": "b", "company_name": "B Co", "website": "https://b.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Blocked", "export_status": "Blocked"},
        {"prospect_id": "a", "company_name": "A Co", "website": "https://a.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Ready", "export_status": "Ready"},
    ])
    assert page.selected_prospect_ids() == ["a"]


def test_removed_prospect_selection_dropped(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    page.set_prospects([
        {"prospect_id": "b", "company_name": "B Co", "website": "https://b.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Blocked", "export_status": "Blocked"},
    ])
    assert page.selected_prospect_ids() == []


def test_new_prospect_not_auto_selected(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    page.set_prospects([
        {"prospect_id": "a", "company_name": "A Co", "website": "https://a.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Ready", "export_status": "Ready"},
        {"prospect_id": "b", "company_name": "B Co", "website": "https://b.com", "resolved_template": "contractor", "template_options": ["contractor"], "opportunity": "Generic", "eligibility": "Blocked", "export_status": "Blocked"},
        {"prospect_id": "c", "company_name": "C Co", "website": "https://c.com", "resolved_template": "dentist", "template_options": ["dentist"], "opportunity": "Generic", "eligibility": "Ready", "export_status": "Blocked"},
    ])
    assert page.selected_prospect_ids() == ["a"]


def test_empty_refresh_clears_selection(tmp_path) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    page.set_prospects([])
    assert page.selected_prospect_ids() == []


def test_export_button_signal_flow_and_save(tmp_path, monkeypatch) -> None:
    _qapplication()

    def fake_generate(request):
        os.makedirs(os.path.dirname(request.output_path), exist_ok=True)
        with open(request.output_path, "w", encoding="utf-8") as handle:
            handle.write("synthetic")
        return MockupResult(
            success=True,
            website=request.url,
            output_path=request.output_path,
            preview_path=request.output_path,
            company_name="A Co",
            headline="Headline",
            cta="CTA",
            quality_score=90,
        )

    _, prospect_controller, batch_controller = _setup(tmp_path, fake_generate=fake_generate)
    assert batch_controller._export_service._prospect_store is batch_controller._service.prospect_store
    assert batch_controller._export_service._job_store is batch_controller._service.job_store
    assert batch_controller._export_service._project_store is batch_controller._service.project_store
    exportable = batch_controller._service.prospect_store.get("a")
    assert exportable is not None
    exportable.email = "owner@a.com"
    batch_controller._service.prospect_store.save()

    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    assert page.selected_prospect_ids() == ["a"]
    batch_controller.queue_selected(page.selected_prospect_ids(), page.selected_templates())
    batch_controller.run_queue()
    _wait_until(lambda: batch_controller.is_running is False)
    _wait_until(lambda: page.export_button.isEnabled() is True)
    assert page.selected_prospect_ids() == ["a"]

    export_eligibility = batch_controller._export_service.check_eligibility("a")
    assert export_eligibility.status != EXPORT_STATUS_BLOCKED

    output_path = os.path.join(str(tmp_path), "export.csv")
    monkeypatch.setattr(
        "gui.views.batch_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (output_path, "CSV files (*.csv)"),
    )
    page.export_button.click()
    _wait_until(lambda: os.path.isfile(output_path), timeout_ms=2000)
    assert os.path.isfile(output_path)
    assert "Campaign CSV exported" in page.message_label.text()
    import csv

    with open(output_path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert any(row.get("prospect_id") == "a" for row in rows)


def test_export_button_cancel_does_not_call_export(tmp_path, monkeypatch) -> None:
    _qapplication()
    _, prospect_controller, batch_controller = _setup(tmp_path)
    page = BatchPage()
    page.set_controller(batch_controller)
    prospect_controller.load()
    batch_controller.refresh()
    page.prospect_table.item(0, BatchPage.COL_SELECT).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)

    calls: list[tuple[list[str], str]] = []
    page.export_requested.connect(lambda ids, path: calls.append((list(ids), path)))
    monkeypatch.setattr(
        "gui.views.batch_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    page.export_button.click()
    _qapplication().processEvents()
    assert calls == []
    assert "cancelled" in page.message_label.text().lower()