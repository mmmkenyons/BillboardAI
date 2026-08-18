"""Qt controller for Sprint 5J/5N batch mockup generation and packaging."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from gui.controllers.prospect_controller import ProspectController
from gui.controllers.profile_resolution_controller import ProfileResolutionController
from gui.models.campaign_package import CampaignPackageResult
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.profile_resolver import effective_scrape_url
from gui.services.prospect_generation import ProspectGenerationService
from gui.workers.prospect_generation_worker import ProspectGenerationWorker
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


class BatchGenerationController(QObject):
    prospects_changed = Signal(object)
    jobs_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)
    running_changed = Signal(bool)
    open_project_requested = Signal(str)
    open_campaign_review_requested = Signal(object)
    export_preview_changed = Signal(object)

    def __init__(
        self,
        *,
        prospect_controller: ProspectController,
        service: ProspectGenerationService,
        resolution_service=None,
    ) -> None:
        super().__init__()
        self._prospect_controller = prospect_controller
        self._service = service
        self._resolution = ProfileResolutionController(
            prospect_store=service.prospect_store,
            service=resolution_service,
        )
        self._resolution.status_message.connect(self.status_message)
        self._resolution.error_message.connect(self.error_message)
        self._resolution.running_changed.connect(self.running_changed)
        self._resolution.results_changed.connect(self._on_resolution_results)
        self._export_service = CampaignExportService(
            prospect_store=service.prospect_store,
            job_store=service.job_store,
            project_store=service.project_store,
        )
        self._package_service = CampaignPackageService(export_service=self._export_service)
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProspectGenerationWorker] = None
        prospect_controller.prospects_changed.connect(self.refresh)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def refresh(self) -> None:
        self.prospects_changed.emit(self._build_prospect_rows())
        self.jobs_changed.emit(self._build_job_rows())
        all_ids = [prospect.prospect_id for prospect in self._prospect_controller.list_prospects()]
        self.export_preview_changed.emit(self._build_export_rows(all_ids))

    def queue_selected(
        self,
        prospect_ids: list[str],
        templates: dict[str, str],
        opportunity_ids: dict[str, str] | None = None,
    ) -> None:
        results = self._service.create_jobs(prospect_ids, templates=templates, opportunity_ids=opportunity_ids)
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

    # ------------------------------------------------------------------
    # Sprint 5Z profile resolution (delegated to the resolution controller)
    # ------------------------------------------------------------------
    def resolve_profiles(self, prospect_ids: list[str]) -> None:
        """Start background profile resolution for the selected prospects."""
        self._resolution.resolve(prospect_ids)

    def set_manual_profile(self, prospect_id: str, url: str) -> None:
        """Persist a manual profile URL override for one prospect."""
        self._resolution.set_manual_profile(prospect_id, url)

    def clear_manual_profile(self, prospect_id: str) -> None:
        """Clear a manual override and restore the automatic result."""
        self._resolution.clear_manual_profile(prospect_id)

    def _on_resolution_results(self, _by_id: dict) -> None:
        # Resolution applied/persisted; reflect new status/URLs in the table.
        self.refresh()

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

    def export_campaign_csv(self, prospect_ids: list[str], output_path: str) -> str:
        exported = self._export_service.export_csv(prospect_ids, output_path)
        self.status_message.emit(f"Campaign CSV exported: {exported}")
        self.refresh()
        return exported

    def build_campaign_package(self, prospect_ids: list[str], destination: str, campaign_name: str | None = None) -> CampaignPackageResult:
        result = self._package_service.build_package(prospect_ids, destination, campaign_name=campaign_name)
        if result.success:
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        return result

    def open_campaign_review(self, prospect_ids: list[str] | None = None) -> None:
        payload = [prospect_id for prospect_id in (prospect_ids or []) if str(prospect_id or "").strip()]
        self.open_campaign_review_requested.emit(payload)

    def open_folder(self, path: str) -> None:
        folder = path or ""
        if not folder or not os.path.isdir(folder):
            self.error_message.emit("Folder does not exist.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as exc:  # noqa: BLE001
            logger.warning("Could not open folder: %s", exc)
            self.error_message.emit(f"Could not open folder:\n{exc}")

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
            export_eligibility = self._export_service.check_eligibility(prospect.prospect_id)
            rows.append(
                {
                    "prospect_id": prospect.prospect_id,
                    "company_name": prospect.company_name,
                    "website": prospect.website,
                    "resolved_template": eligibility.resolved_template,
                    "template_options": ["contractor", "dentist", "realtor"],
                    "opportunity": self._service.recommended_opportunity_label(prospect.prospect_id),
                    "eligibility": "Ready" if eligibility.eligible else ", ".join(eligibility.reasons),
                    "export_status": export_eligibility.status.title(),
                    "resolution_status": prospect.resolution_status,
                    "resolution_confidence": prospect.resolution_confidence,
                    "resolved_profile_url": prospect.resolved_profile_url,
                    "manual_profile_url": prospect.manual_profile_url,
                    "effective_scrape_url": effective_scrape_url(prospect),
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
                    "opportunity": job.metadata.get("opportunity_label", "Generic"),
                    "status": job.status,
                    "result": job.result_path or job.error,
                }
            )
        return rows

    def _build_export_rows(self, prospect_ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        for preview in self._export_service.preview_rows(prospect_ids):
            rows.append(
                {
                    "prospect_id": preview.prospect_id,
                    "company_name": preview.company,
                    "email": preview.email,
                    "status": preview.status,
                    "reasons": "; ".join(preview.reasons or preview.warnings),
                    "generation_job_id": preview.generation_job_id,
                    "project_id": preview.project_id,
                }
            )
        return rows