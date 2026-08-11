"""Sprint 5A prospect workspace controller (Qt).

Coordinates the prospect workspace views with the Qt-free
:class:`~gui.services.prospect_workspace.ProspectWorkspaceService`. Exposes Qt
signals, invokes the service, coordinates the selected prospect, surfaces
errors, and notifies views after load/import/save. No field parsing or business
rules live here — those belong to the service layer.

Threading: prospect operations (load, CRUD, CSV import) are local JSON and fast,
so no worker threads are created (kept simple per the sprint brief).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from gui.models.prospect import Prospect
from gui.models.prospect_store import ProspectCorruptionError, ProspectStore
from gui.services.prospect_csv_import import ProspectImportError, ProspectImportResult
from gui.services.prospect_workspace import (
    ProspectValidationError,
    ProspectWorkspaceService,
)
from gui.controllers.research_controller import ResearchController

logger = logging.getLogger(__name__)


class ProspectController(QObject):
    """Routes prospect workspace actions to the service and drives the UI."""

    # Public signals (views connect to these).
    prospects_loaded = Signal()
    prospects_changed = Signal()  # after any mutation / import / save
    error_message = Signal(str)
    status_message = Signal(str)
    open_project_requested = Signal(str)  # ask the app to open a Project workspace

    def __init__(
        self,
        service: Optional[ProspectWorkspaceService] = None,
        path: Optional[str] = None,
    ) -> None:
        super().__init__()
        if service is None:
            service = ProspectWorkspaceService(store=ProspectStore(path=path))
        self._service = service
        self._selected_id: Optional[str] = None
        # Sprint 5B: batch research queue controller reusing the same prospect
        # store/service so prospect research_status stays in sync.
        self._research = ResearchController(prospect_service=service)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def service(self) -> ProspectWorkspaceService:
        return self._service

    @property
    def store(self) -> ProspectStore:
        return self._service.store

    @property
    def research(self) -> ResearchController:
        """The batch research queue controller for this prospects workspace."""
        return self._research

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def select(self, prospect_id: Optional[str]) -> None:
        """Track the currently selected prospect id."""
        self._selected_id = prospect_id

    def open_project(self, project_id: Optional[str]) -> None:
        """Request the app to open an existing Project workspace."""
        if project_id:
            self.open_project_requested.emit(str(project_id))

    # ------------------------------------------------------------------
    # Load / refresh
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load prospects (empty when missing); surface corruption clearly."""
        try:
            self._service.load()
            self._research.load()
            self.prospects_loaded.emit()
            self.prospects_changed.emit()
        except ProspectCorruptionError as exc:
            logger.warning("Prospect load failed (corrupt): %s", exc)
            self.error_message.emit(f"Corrupt prospects file: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any load failure
            logger.warning("Prospect load failed: %s", exc)
            self.error_message.emit(f"Could not load prospects: {exc}")

    def reload(self) -> None:
        self.load()

    # ------------------------------------------------------------------
    # Queries (delegate to service)
    # ------------------------------------------------------------------

    def list_prospects(self) -> List[Prospect]:
        try:
            return self._service.list_prospects()
        except ProspectCorruptionError as exc:
            self.error_message.emit(f"Corrupt prospects file: {exc}")
            return []

    def get_prospect(self, prospect_id: str) -> Optional[Prospect]:
        return self._service.get_prospect(prospect_id)

    def categories(self) -> List[str]:
        try:
            return self._service.categories()
        except ProspectCorruptionError:
            return []

    def statuses(self) -> List[str]:
        return self._service.statuses()

    def search(self, query: str) -> List[Prospect]:
        try:
            return self._service.search(query)
        except ProspectCorruptionError as exc:
            self.error_message.emit(f"Corrupt prospects file: {exc}")
            return []

    def filter_by_status(self, status: str) -> List[Prospect]:
        if not status or status == "ALL":
            return self.list_prospects()
        try:
            return self._service.list_by_status(status)
        except ProspectCorruptionError:
            return []

    def filter_by_category(self, category: str) -> List[Prospect]:
        if not category or category == "ALL":
            return self.list_prospects()
        try:
            return self._service.list_by_category(category)
        except ProspectCorruptionError:
            return []
    # ------------------------------------------------------------------
    # Mutations (service handles logic + persistence; this surfaces errors)
    # ------------------------------------------------------------------

    def create_prospect(self, **kw) -> Optional[Prospect]:
        return self._mutate(
            lambda: self._service.create_prospect(**kw), "Prospect added."
        )

    def update_prospect(self, prospect_id: str, **kw) -> Optional[Prospect]:
        return self._mutate(
            lambda: self._service.update_prospect(prospect_id, **kw),
            "Prospect saved.",
        )

    def archive_prospect(self, prospect_id: str) -> Optional[Prospect]:
        return self._mutate(
            lambda: self._service.archive_prospect(prospect_id),
            "Prospect archived.",
        )

    def set_status(self, prospect_id: str, status: str) -> Optional[Prospect]:
        return self._mutate(
            lambda: self._service.set_status(prospect_id, status),
            f"Status set to {status}.",
        )

    # ------------------------------------------------------------------
    # CSV import
    # ------------------------------------------------------------------

    def import_csv(self, content: str) -> Optional[ProspectImportResult]:
        """Import CSV text content; emit signals and return the result.

        Returns None on failure (error already emitted).
        """
        try:
            result = self._service.import_csv(content)
        except ProspectImportError as exc:
            logger.warning("CSV import failed: %s", exc)
            self.error_message.emit(str(exc))
            return None
        except ProspectCorruptionError as exc:
            self.error_message.emit(f"Corrupt prospects file: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("CSV import failed: %s", exc)
            self.error_message.emit(f"Import failed: {exc}")
            return None
        self.prospects_changed.emit()
        self._emit_import_summary(result)
        return result

    def import_csv_file(self, path: str) -> Optional[ProspectImportResult]:
        """Import a CSV file; emit signals and return the result."""
        try:
            result = self._service.import_csv_file(path)
        except ProspectImportError as exc:
            logger.warning("CSV import failed: %s", exc)
            self.error_message.emit(str(exc))
            return None
        except ProspectCorruptionError as exc:
            self.error_message.emit(f"Corrupt prospects file: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("CSV import failed: %s", exc)
            self.error_message.emit(f"Import failed: {exc}")
            return None
        self.prospects_changed.emit()
        self._emit_import_summary(result)
        return result

    def preview_mapping(self, content: str) -> Dict[str, str]:
        """Detect the column mapping without importing (for the import dialog)."""
        from gui.services import prospect_csv_import as imp

        try:
            rows = imp._read_all_rows(content)
        except Exception:  # noqa: BLE001
            return {}
        headers = imp._extract_headers(rows)
        return imp.detect_mapping(headers)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _mutate(self, fn, success: str) -> Any:
        try:
            result = fn()
        except ProspectValidationError as exc:
            logger.warning("Prospect validation failed: %s", exc)
            self.error_message.emit(str(exc))
            return None
        except ProspectCorruptionError as exc:
            self.error_message.emit(f"Corrupt prospects file: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("Prospect mutation failed: %s", exc)
            self.error_message.emit(f"Save failed: {exc}")
            return None
        self.prospects_changed.emit()
        self.status_message.emit(success)
        return result

    def _emit_import_summary(self, result: ProspectImportResult) -> None:
        self.status_message.emit(
            f"Imported {result.imported}, merged {result.merged}, "
            f"invalid {result.invalid}, skipped {result.skipped}."
        )