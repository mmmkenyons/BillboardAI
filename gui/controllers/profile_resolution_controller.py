"""Sprint 5Z profile resolution controller (Qt).

Bridges the desktop UI to the Qt-free
:class:`~gui.services.profile_resolver.ProfileResolverService`. Automatic
resolution runs on a background ``QThread`` through
:class:`~gui.workers.profile_resolution_worker.ProfileResolutionWorker` so the
GUI never blocks on network; completed prospects are persisted on the GUI
thread. Manual URL set/clear are local, fast, synchronous store operations.

Signals (delivered on the GUI thread for queued connections):

- ``results_changed(object)`` — dict ``prospect_id -> row dict`` propagated once
  per operation (no duplicate signal execution).
- ``running_changed(bool)`` — a resolution batch started / completed.
- ``status_message(str)`` / ``error_message(str)`` — user-facing status.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from gui.models.prospect import Prospect
from gui.models.prospect_store import ProspectStore
from gui.services.profile_resolver import (
    ProfileResolverService,
    effective_scrape_url,
)
from gui.workers.profile_resolution_worker import ProfileResolutionWorker

logger = logging.getLogger(__name__)


class ProfileResolutionController(QObject):
    """Coordinates profile resolution actions with the Qt-free service."""

    results_changed = Signal(object)  # dict prospect_id -> row dict
    running_changed = Signal(bool)
    status_message = Signal(str)
    error_message = Signal(str)

    def __init__(
        self,
        prospect_store: ProspectStore,
        service: Optional[ProfileResolverService] = None,
    ) -> None:
        super().__init__()
        self._store = prospect_store
        self._service = service if service is not None else ProfileResolverService()
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProfileResolutionWorker] = None
        self._last_results: Dict[str, dict] = {}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def last_results(self) -> Dict[str, dict]:
        return dict(self._last_results)

    # ------------------------------------------------------------------
    # Automatic resolution (background)
    # ------------------------------------------------------------------
    def resolve(self, prospect_ids: List[str]) -> None:
        """Start a background resolution batch for the given prospect ids.

        Returns immediately (thread start); nothing on its own blocks the GUI
        thread and no network runs on the GUI thread.
        """
        if self.is_running:
            self.status_message.emit("Profile resolution is already running.")
            return
        prospects: List[Prospect] = []
        for prospect_id in prospect_ids:
            prospect = self._store.get(str(prospect_id))
            if prospect is not None and (prospect.website or "").strip():
                prospects.append(prospect)
        if not prospects:
            self.status_message.emit("No prospects with a parent website selected.")
            return

        worker = ProfileResolutionWorker(self._service, prospects)
        self._thread = QThread(self)
        worker.moveToThread(self._thread)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        self._thread.started.connect(worker.run)
        self._worker = worker
        self._thread.start()
        self.running_changed.emit(True)
        self.status_message.emit(
            f"Resolving profiles for {len(prospects)} prospect(s) in the background..."
        )

    # ------------------------------------------------------------------
    # Manual override (local, synchronous, persisted)
    # ------------------------------------------------------------------
    def set_manual_profile(self, prospect_id: str, url: str) -> None:
        prospect = self._store.get(str(prospect_id))
        if prospect is None:
            self.error_message.emit("Prospect not found.")
            return
        try:
            self._service.set_manual_profile_url(prospect, url)
        except ValueError as exc:
            self.error_message.emit(str(exc))
            return
        self._store.update(prospect)
        self._store.save()
        self.status_message.emit("Manual profile URL saved.")
        self.results_changed.emit({prospect.prospect_id: self._row(prospect)})

    def clear_manual_profile(self, prospect_id: str) -> None:
        prospect = self._store.get(str(prospect_id))
        if prospect is None:
            self.error_message.emit("Prospect not found.")
            return
        self._service.clear_manual_profile_url(prospect)
        self._store.update(prospect)
        self._store.save()
        self.status_message.emit("Manual profile URL cleared — automatic result restored.")
        self.results_changed.emit({prospect.prospect_id: self._row(prospect)})


# ------------------------------------------------------------------
    # Slots (GUI thread)
    # ------------------------------------------------------------------
    def _on_progress(self, prospect_id: str, status: str) -> None:
        # Optional incremental status; does NOT emit results (single emit per batch).
        return

    def _on_worker_finished(self, payload: object) -> None:
        self._cleanup_thread()
        prospects, results = payload
        by_id: Dict[str, dict] = {}
        for prospect, _result in zip(prospects, results):
            try:
                self._store.update(prospect)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist resolution for %s: %s",
                               prospect.prospect_id, exc)
            by_id[prospect.prospect_id] = self._row(prospect)
        self._store.save()
        self._last_results = by_id
        self.running_changed.emit(False)
        self.results_changed.emit(by_id)
        statuses = sorted({row["resolution_status"] for row in by_id.values()})
        summary = ", ".join(statuses) if statuses else "none"
        self.status_message.emit(f"Profile resolution complete: {summary}.")

    def _on_worker_failed(self, error: str) -> None:
        self._cleanup_thread()
        self.running_changed.emit(False)
        self.error_message.emit(f"Profile resolution failed: {error}")

    def _cleanup_thread(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)

    def _row(self, prospect: Prospect) -> dict:
        return {
            "prospect_id": prospect.prospect_id,
            "resolution_status": prospect.resolution_status,
            "resolution_confidence": prospect.resolution_confidence,
            "resolved_profile_url": prospect.resolved_profile_url,
            "manual_profile_url": prospect.manual_profile_url,
            "effective_scrape_url": effective_scrape_url(prospect),
        }