"""Sprint 5B research queue controller (Qt).

Bridges the Qt widgets to the Qt-free
:class:`~gui.services.research_queue.ResearchQueueService`, and runs batch
execution on a background ``QThread`` so the GUI never blocks on a browser.

Signals (delivered on the GUI thread because the worker executes in another
thread, so Qt uses queued connections automatically):

- ``progress(stage, company)`` — current active job's stage.
- ``queue_changed``          — job list / counts changed.
- ``counts_changed(dict)``   — summary counts for the queue UI.
- ``running_changed(bool)``  — worker started / stopped.
- ``batch_finished(object)`` — a ResearchBatchResult.
- ``error_message(str)`` / ``status_message(str)``.
- ``open_project_requested(str)`` — ask the app to open a Project in the
  existing Project Workspace.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from gui.models.research_job import ResearchJob
from gui.services.prospect_workspace import ProspectWorkspaceService
from gui.services.research_queue import ResearchQueueService

logger = logging.getLogger(__name__)


class ResearchQueueWorker(QObject):
    """Runs a bounded queue batch off the GUI thread (mirrors existing workers)."""

    progress = Signal(str, str, str)  # stage, company, job_id
    finished = Signal(object)  # ResearchBatchResult
    failed = Signal(str)

    def __init__(
        self,
        service: ResearchQueueService,
        limit: int,
        concurrency: int,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self._service = service
        self._limit = limit
        self._concurrency = concurrency
        self._stop_event = stop_event

    def run(self) -> None:
        try:

            def _on_progress(stage: str, company: str, job_id: str) -> None:
                self.progress.emit(stage, company, job_id)

            summary = self._service.run_batch(
                limit=self._limit,
                concurrency=self._concurrency,
                stop_event=self._stop_event,
                progress=_on_progress,
            )
            self.finished.emit(summary)
        except Exception as exc:  # noqa: BLE001 - never crash the GUI
            logger.exception("Research batch failed")
            self.failed.emit(str(exc))


class ResearchController(QObject):
    """Coordinates queue actions with the Qt-free service + a QThread."""

    progress = Signal(str, str)  # stage, company
    queue_changed = Signal()
    counts_changed = Signal(object)  # dict
    running_changed = Signal(bool)
    batch_finished = Signal(object)  # ResearchBatchResult
    error_message = Signal(str)
    status_message = Signal(str)
    open_project_requested = Signal(str)

    def __init__(
        self,
        service: Optional[ResearchQueueService] = None,
        prospect_service: Optional[ProspectWorkspaceService] = None,
    ) -> None:
        super().__init__()
        if service is None:
            service = ResearchQueueService(prospect_service=prospect_service)
        self._service = service
        self._thread: Optional[QThread] = None
        self._worker: Optional[ResearchQueueWorker] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def service(self) -> ResearchQueueService:
        return self._service

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def load(self) -> None:
        try:
            self._service.ensure_loaded()
            self.queue_changed.emit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Research queue load failed: %s", exc)
            self.error_message.emit(f"Could not load research queue: {exc}")

    def list_jobs(self) -> List[ResearchJob]:
        try:
            return self._service.list_jobs()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Research queue listing failed: %s", exc)
            return []

    def counts(self) -> Dict[str, int]:
        try:
            return self._service.counts()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Research queue counts failed: %s", exc)
            return {}
# ------------------------------------------------------------------
    # Queue actions
    # ------------------------------------------------------------------
    def enqueue(self, prospect_id: str) -> bool:
        reason: List[str] = []
        try:
            ok = self._service.enqueue_prospect(prospect_id, reason=reason)
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Enqueue failed: {exc}")
            return False
        self._after_change()
        self.status_message.emit("Queued for research." if ok else "; ".join(reason))
        return ok

    def enqueue_all(self) -> int:
        try:
            count = self._service.enqueue_ready_prospects()
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Enqueue all failed: {exc}")
            return 0
        self._after_change()
        self.status_message.emit(f"Queued {count} ready prospects for research.")
        return count

    def retry_failed(self, limit: Optional[int] = None) -> int:
        try:
            count = self._service.retry_failed_jobs(limit=limit)
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Retry failed: {exc}")
            return 0
        self._after_change()
        self.status_message.emit(f"Re-queued {count} failed job(s) for retry.")
        return count

    def cancel(self, job_id: str) -> bool:
        try:
            ok = self._service.cancel_job(job_id)
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Cancel failed: {exc}")
            return False
        self._after_change()
        self.status_message.emit(
            "Cancelled queued job." if ok else "Job could not be cancelled."
        )
        return ok

    def cancel_pending(self) -> int:
        try:
            count = self._service.cancel_pending()
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Cancel failed: {exc}")
            return 0
        self._after_change()
        self.status_message.emit(f"Cancelled {count} queued job(s).")
        return count
# ------------------------------------------------------------------
    # Execution (background)
    # ------------------------------------------------------------------
    def research_next(self, count: int = 1, concurrency: int = 1) -> bool:
        """Start a background batch run of up to ``count`` jobs."""
        if self.is_running:
            self.status_message.emit("Research already running.")
            return False
        self._stop_event.clear()
        worker = ResearchQueueWorker(
            service=self._service,
            limit=int(count or 1),
            concurrency=int(concurrency or 1),
            stop_event=self._stop_event,
        )
        self._thread = QThread(self)
        worker.moveToThread(self._thread)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        self._thread.started.connect(worker.run)
        self._worker = worker
        self._thread.start()
        self.running_changed.emit(True)
        self.status_message.emit("Research running in the background...")
        return True

    def stop_after_current(self) -> None:
        """Cooperatively stop after the currently running job. Queued jobs remain."""
        self._stop_event.set()
        self.status_message.emit("Will stop after the current job.")

    # ------------------------------------------------------------------
    # Project navigation
    # ------------------------------------------------------------------
    def open_project(self, project_id: str) -> None:
        if project_id:
            self.open_project_requested.emit(project_id)

    # ------------------------------------------------------------------
    # Slots (GUI thread)
    # ------------------------------------------------------------------
    def _on_progress(self, stage: str, company: str, job_id: str) -> None:
        self.progress.emit(stage, company)

    def _on_worker_finished(self, summary: object) -> None:
        self._cleanup_thread()
        self.running_changed.emit(False)
        self._after_change()
        self.batch_finished.emit(summary)
        s = getattr(summary, "claimed", 0)
        self.status_message.emit(
            f"Research pass complete: {s} job(s) processed (see queue)."
        )

    def _on_worker_failed(self, error: str) -> None:
        self._cleanup_thread()
        self.running_changed.emit(False)
        self._after_change()
        self.error_message.emit(f"Research batch failed: {error}")

    def _cleanup_thread(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)

    def _after_change(self) -> None:
        self.queue_changed.emit()
        self.counts_changed.emit(self.counts())