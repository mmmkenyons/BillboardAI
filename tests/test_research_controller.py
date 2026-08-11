"""Sprint 5B research GUI controller offscreen test suite.

Exercises the ResearchController and ProspectWorkspacePage wires using a
FakePipeline (no network). Runs offscreen via ``QT_QPA_PLATFORM=offscreen``.
"""
from __future__ import annotations

import os

import pytest

from engine.ad_concept import AdConcept
from engine.brand_profile import BrandProfile
from engine.message_strategy import MessageStrategy
from gui.controllers.research_controller import ResearchController
from gui.models.prospect_store import ProspectStore
from gui.models.research_job import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCEEDED,
)
from gui.models.research_job_store import ResearchQueueStore
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.services.research_pipeline import ResearchResult
from gui.services.research_queue import ResearchQueueService


# ---------------------------------------------------------------------------
# Fake pipeline (same pattern as test_research_queue.py)
# ---------------------------------------------------------------------------


class _FakePipeline:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.calls: list = []

    def run(self, prospect, progress_callback=None):
        self.calls.append(prospect.prospect_id)
        if callable(progress_callback):
            progress_callback("Scraping")
        if self.success:
            return ResearchResult(
                success=True,
                prospect_id=prospect.prospect_id,
                project_id="proj-fake",
                brand_profile=BrandProfile(company_name=prospect.company_name),
                strategies=[MessageStrategy()],
                concepts=[AdConcept()],
            )
        return ResearchResult(
            success=False,
            prospect_id=prospect.prospect_id,
            error="boom",
            error_type="scrape_transient",
            retryable=True,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _qapplication():
    """Return or create a QApplication (offscreen)."""
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        pytest.skip("PySide6 not available")
    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


def _ready_prospect(psvc, name="Jim Woods Roofing", site="jimwoodsroofing.com") -> str:
    return psvc.create_prospect(company_name=name, website=site).prospect_id


def _make_controller(tmp_path, pipeline=None):
    """Build a ProspectController + ResearchController with a fake pipeline.

    Both controllers share a single ProspectWorkspaceService instance so
    prospects created through the page are visible to the research queue.
    """
    from gui.controllers.prospect_controller import ProspectController

    pipe = pipeline if pipeline is not None else _FakePipeline(success=True)
    pc = ProspectController(path=str(tmp_path / "prospects.json"))
    psvc = pc.service  # single shared prospect service
    jstore = ResearchQueueStore(path=str(tmp_path / "queue.json"))
    rsvc = ResearchQueueService(
        prospect_service=psvc,
        job_store=jstore,
        pipeline=pipe,
        max_attempts=2,
        retry_delays=(0, 0),
    )
    rsvc.ensure_loaded()

    pc._research = ResearchController(service=rsvc, prospect_service=psvc)
    psvc.load()
    return pc


# ---------------------------------------------------------------------------
# CONTROLLER TESTS
# ---------------------------------------------------------------------------


class TestResearchController:
    def test_enqueue_selected(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        pid = _ready_prospect(pc.service)
        ok = pc.research.enqueue(pid)
        assert ok is True
        jobs = pc.research.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].status == STATUS_PENDING

    def test_enqueue_all_ready(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        _ready_prospect(pc.service, "A", "a.com")
        _ready_prospect(pc.service, "B", "b.com")
        count = pc.research.enqueue_all()
        assert count == 2

    def test_research_next(self, tmp_path) -> None:
        app = _qapplication()
        pc = _make_controller(tmp_path)
        _ready_prospect(pc.service, "A", "a.com")
        _ready_prospect(pc.service, "B", "b.com")
        pc.research.enqueue_all()
        ok = pc.research.research_next(count=2, concurrency=1)
        assert ok is True
        # Pump the event loop so the queued `finished` signal (worker thread ->
        # main thread) is delivered and the QThread is cleaned up.
        import time

        deadline = time.time() + 10.0
        while time.time() < deadline and pc.research.is_running:
            app.processEvents()
            time.sleep(0.01)
        assert pc.research.is_running is False
        jobs = pc.research.list_jobs()
        assert all(j.status == STATUS_SUCCEEDED for j in jobs)

    def test_counts(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        pid = _ready_prospect(pc.service)
        pc.research.enqueue(pid)
        c = pc.research.counts()
        assert isinstance(c, dict)
        assert c.get("queued", 0) >= 1

    def test_cancel_queued(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        pid = _ready_prospect(pc.service)
        pc.research.enqueue(pid)
        job = pc.research.list_jobs()[0]
        ok = pc.research.cancel(job.job_id)
        assert ok is True
        cancelled = next((j for j in pc.research.list_jobs() if j.job_id == job.job_id), None)
        assert cancelled is not None
        assert cancelled.status == STATUS_CANCELLED

    def test_cancel_pending(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        _ready_prospect(pc.service, "A", "a.com")
        _ready_prospect(pc.service, "B", "b.com")
        pc.research.enqueue_all()
        count = pc.research.cancel_pending()
        assert count == 2

    def test_stop_after_current(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        _ready_prospect(pc.service, "A", "a.com")
        pc.research.enqueue_all()
        pc.research.stop_after_current()  # no-op when idle; must not crash
        assert pc.research.is_running is False

    def test_is_running_property(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        assert pc.research.is_running is False

    def test_list_jobs_roundtrip(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        pid = _ready_prospect(pc.service)
        pc.research.enqueue(pid)
        jobs = pc.research.list_jobs()
        assert len(jobs) == 1
        found = next((j for j in pc.research.list_jobs() if j.job_id == jobs[0].job_id), None)
        assert found is not None
        assert found.prospect_id == pid

    def test_open_project_requested_signal(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        emitted: list = []
        pc.research.open_project_requested.connect(emitted.append)
        pc.research.open_project("proj-123")
        assert emitted == ["proj-123"]

    def test_retry_failed(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        pid = _ready_prospect(pc.service)
        pc.research.enqueue(pid)
        svc = pc.research._service
        job = svc.claim_next_job()
        svc.complete_job(
            job,
            ResearchResult(
                success=False, prospect_id=pid, error="x",
                error_type="invalid_url", retryable=False,
            ),
        )
        assert job.status == STATUS_FAILED
        count = pc.research.retry_failed()
        assert count == 1
        retried = next((j for j in pc.research.list_jobs() if j.job_id == job.job_id), None)
        assert retried is not None
        assert retried.status == STATUS_PENDING


# ---------------------------------------------------------------------------
# PAGE TESTS (wired controller)
# ---------------------------------------------------------------------------


class TestProspectWorkspacePageResearch:
    def test_page_constructs_offscreen(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        page = ProspectWorkspacePage()
        page.set_controller(pc)
        assert page._controller is not None
        assert page.queue_table is not None
        assert page.queue_button is not None
        assert page.queue_all_button is not None
        assert page.run_button is not None
        assert page.stop_button is not None
        assert page.retry_button is not None
        assert page.cancel_button is not None
        assert page.open_project_button is not None

    def test_buttons_initial_state(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        page = ProspectWorkspacePage()
        page.set_controller(pc)
        # Not running: run enabled, stop disabled.
        page._on_research_running(False)
        assert page.run_button.isEnabled() is True
        assert page.stop_button.isEnabled() is False
        # Running: run disabled, stop enabled, progress label set.
        page._on_research_running(True)
        assert page.run_button.isEnabled() is False
        assert page.stop_button.isEnabled() is True
        assert "Research in progress" in page.research_progress_label.text()
        # Back to idle.
        page._on_research_running(False)
        assert page.run_button.isEnabled() is True
        assert page.stop_button.isEnabled() is False

    def test_queue_all_populates_table(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        _ready_prospect(pc.service, "A", "a.com")
        _ready_prospect(pc.service, "B", "b.com")
        page = ProspectWorkspacePage()
        page.set_controller(pc)
        pc.research.enqueue_all()
        page._refresh_research_panel()
        assert page.queue_table.rowCount() == 2

    def test_research_counts_label(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        pid = _ready_prospect(pc.service)
        page = ProspectWorkspacePage()
        page.set_controller(pc)
        pc.research.enqueue(pid)
        page._refresh_research_panel()
        text = page.research_counts_label.text()
        assert "Queued" in text

    def test_successful_job_exposes_open_project(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        pid = _ready_prospect(pc.service)
        pc.research.enqueue(pid)
        job = pc.research._service.claim_next_job()
        pc.research._service.complete_job(
            job,
            ResearchResult(success=True, prospect_id=pid, project_id="proj-real"),
        )
        page = ProspectWorkspacePage()
        page.set_controller(pc)
        page._refresh_research_panel()
        assert page.queue_table.rowCount() == 1
        page.queue_table.selectRow(0)
        assert page.open_project_button.isEnabled() is True

    def test_progress_label_update(self, tmp_path) -> None:
        _qapplication()
        pc = _make_controller(tmp_path)
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        page = ProspectWorkspacePage()
        page.set_controller(pc)
        page._on_research_progress("Scraping", "Acme")
        assert "Acme" in page.research_progress_label.text()
        assert "Scraping" in page.research_progress_label.text()

    def test_unwired_actions_no_crash(self, tmp_path) -> None:
        _qapplication()
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        page = ProspectWorkspacePage()
        page._on_queue_selected()
        page._on_queue_all()
        page._on_research_next()
        page._on_retry_failed()
        page._on_cancel_selected()
        page._on_stop_after_current()
        page._on_open_project()
        assert True
