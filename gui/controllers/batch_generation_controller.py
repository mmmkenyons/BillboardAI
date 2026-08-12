"""Qt controller for Sprint 5J batch mockup generation."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from gui.controllers.prospect_controller import ProspectController
from gui.services.prospect_generation import ProspectGenerationService
from gui.workers.prospect_generation_worker import ProspectGenerationWorker

logger = logging.getLogger(__name__)


class BatchGenerationController(QObject):
    prospects_changed = Signal(object)
    jobs_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)
    running_changed = Signal(bool)
    open_project_requested = Signal(str)

    def __init__(
        self,
        *,
        prospect_controller: ProspectController,
        service: ProspectGenerationService,
    ) -> None:
        super().__init__()
        self._prospect_controller = prospect_controller
        self._service = service
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProspectGenerationWorker] = None
        prospect_controller.prospects_changed.connect(self.refresh)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def refresh(self) -> None:
        self.prospects_changed.emit(self._build_prospect_rows())
        self.jobs_changed.emit(self._build_job_rows())

    def queue_selected(self, prospect_ids: list[str], templates: dict[str, str]) -> None:
        results = self._service.create_jobs(prospect_ids, templates=templates)
        rejected = []
        queued = 0
        for result in results:
            if result.job is not None:
                queued += 1
            elif result.reasons:
                rejected.append(f"{result.prospect_id}: {', '.join(result.reasons)}")
        self.refresh()
        if queued:
            self.status_message.emit(f"Queued {queued} generation job(s).")
        if rejected:
            self.error_message.emit("; ".join(rejected))

    def run_queue(self) -> None:
        if self.is_running:
            self.status_message.emit("Batch generation is already running.")
            return
        queued_ids = [job.id for job in self._service.list_jobs() if job.status == "QUEUED"]
        if not queued_ids:
            self.status_message.emit("No queued jobs to run.")
            self.refresh()
            return
        thread = QThread()
        worker = ProspectGenerationWorker(self._service, queued_ids)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_worker)
        self._thread = thread
        self._worker = worker
        self.running_changed.emit(True)
        self.status_message.emit("Running batch generation queue...")
        self.refresh()
        thread.start()

    def open_project_for_prospect(self, prospect_id: str) -> None:
        prospect = self._service.prospect_store.get(prospect_id)
        if prospect is None:
            self.error_message.emit("Prospect not found.")
            return
        project_id = str(prospect.metadata.get("project_id") or "")
        if not project_id:
            self.error_message.emit("No generated project is associated with this prospect.")
            return
        self.open_project_requested.emit(project_id)

    def _on_worker_progress(self, _job_id: str, status: str) -> None:
        self.status_message.emit(f"Job update: {status}")
        self.refresh()

    def _on_worker_finished(self, _results: object) -> None:
        self.status_message.emit("Batch generation complete.")
        self.refresh()

    def _on_worker_failed(self, error: str) -> None:
        logger.error("Batch generation worker failed: %s", error)
        self.error_message.emit(f"Batch generation failed: {error}")
        self.refresh()

    def _cleanup_worker(self) -> None:
        self.running_changed.emit(False)
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(3000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def _build_prospect_rows(self) -> list[dict]:
        rows: list[dict] = []
        for prospect in self._prospect_controller.list_prospects():
            eligibility = self._service.check_eligibility(prospect.prospect_id)
            rows.append(
                {
                    "prospect_id": prospect.prospect_id,
                    "company_name": prospect.company_name,
                    "website": prospect.website,
                    "resolved_template": eligibility.resolved_template,
                    "template_options": ["contractor", "dentist", "realtor"],
                    "eligibility": "Ready" if eligibility.eligible else ", ".join(eligibility.reasons),
                }
            )
        return rows

    def _build_job_rows(self) -> list[dict]:
        rows: list[dict] = []
        for job in self._service.list_jobs():
            prospect = self._service.prospect_store.get(job.prospect_id)
            rows.append(
                {
                    "prospect_id": job.prospect_id,
                    "company_name": prospect.company_name if prospect is not None else job.metadata.get("company_name", ""),
                    "template": job.template,
                    "status": job.status,
                    "result": job.result_path or job.error,
                }
            )
        return rows