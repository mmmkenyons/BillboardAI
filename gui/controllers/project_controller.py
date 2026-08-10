"""Sprint 3B project workspace controller (Qt).

Coordinates the project workspace views with the Qt-free
:class:`~gui.services.project_workspace.ProjectWorkspaceService`. Owns the
currently open :class:`~gui.models.project.Project` and mediates all
workspace actions (open, select concept, overrides, status, mockup
generation). All business logic lives in the service; the controller adds
threading for expensive generation and emits signals the views connect to.

Threading contract mirrors the existing generation/re-render workers: a
``QObject`` worker is moved to a ``QThread`` and finished/failed signals are
queued to the GUI thread, so widgets are never touched from a worker thread.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from gui.models.project import Project
from gui.services.project_workspace import (
    PROJECT_STATUSES,
    SUPPORTED_OVERRIDES,
    ProjectWorkspaceService,
)
from gui.workers.mockup_generation_worker import MockupGenerationWorker

logger = logging.getLogger(__name__)


class ProjectWorkspaceController(QObject):
    """Routes project workspace actions to the service and drives the UI."""

    # Public signals (views connect to these).
    project_opened = Signal(object)  # Project
    project_closed = Signal()
    project_updated = Signal()  # after any mutation (selection/override/status)
    artifacts_changed = Signal()  # after mockup generation
    projects_changed = Signal()  # after archive (list changed)
    error_message = Signal(str)
    status_message = Signal(str)
    progress_changed = Signal(int, str)
    navigate = Signal(str)  # "projects" | "workspace" | "home"
    generation_started = Signal()
    generation_finished = Signal()

    def __init__(
        self,
        service: Optional[ProjectWorkspaceService] = None,
        store_root: Optional[str] = None,
    ) -> None:
        super().__init__()
        if service is None:
            from gui.models.project_store import ProjectStore

            service = ProjectWorkspaceService(store=ProjectStore(root=store_root))
        self._service = service
        self._project: Optional[Project] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[MockupGenerationWorker] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def service(self) -> ProjectWorkspaceService:
        return self._service

    @property
    def project(self) -> Optional[Project]:
        return self._project

    @property
    def is_generating(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # ------------------------------------------------------------------
    # Project listing / opening
    # ------------------------------------------------------------------
    def list_projects(self) -> List[Project]:
        """Return all persisted projects (called by the project browser)."""
        return self._service.list_projects()

    def open_project(self, project_id: str) -> None:
        """Open a project from the store. Never scrapes / regenerates."""
        try:
            project = self._service.open_project(project_id)
            self._project = project
            self.project_opened.emit(project)
            self.navigate.emit("workspace")
            self.status_message.emit(
                f"Opened {project.company or project.domain or project.name}"
            )
        except Exception as exc:  # noqa: BLE001 - never crash the GUI
            logger.exception("Failed to open project %s", project_id)
            self.error_message.emit(f"Could not open project:\n{exc}")

    def close_project(self) -> None:
        """Close the current project and return to the project browser."""
        self._project = None
        self.project_closed.emit()
        self.navigate.emit("projects")

    def back_to_projects(self) -> None:
        """Navigate back to the project browser without closing the workspace data."""
        self.navigate.emit("projects")

    def archive_project(self, project_id: str) -> None:
        """Archive a project (non-destructive) and refresh the list."""
        try:
            self._service.archive_project(project_id)
            if self._project is not None and self._project.id == project_id:
                self._project = None
                self.project_closed.emit()
            self.projects_changed.emit()
            self.status_message.emit("Project archived.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to archive project %s", project_id)
            self.error_message.emit(f"Could not archive project:\n{exc}")

    # ------------------------------------------------------------------
    # Concept selection
    # ------------------------------------------------------------------
    def select_concept(self, concept_id: str) -> None:
        """Select an AdConcept, persist, and emit refresh."""
        if self._project is None:
            return
        try:
            self._service.select_concept(self._project, concept_id)
            self.project_updated.emit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to select concept")
            self.error_message.emit(str(exc))

    # ------------------------------------------------------------------
    # Overrides (Project.user_overrides only)
    # ------------------------------------------------------------------
    def set_override(self, field: str, value: str) -> None:
        """Persist a user override for the current project."""
        if self._project is None:
            return
        if field not in SUPPORTED_OVERRIDES:
            self.error_message.emit(f"Unsupported override field: {field}")
            return
        try:
            self._service.set_override(self._project, field, value)
            self.project_updated.emit()
            self.status_message.emit(f"{field} override saved.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to set override")
            self.error_message.emit(f"Could not save override:\n{exc}")

    def reset_override(self, field: str) -> None:
        """Remove a user override for the current project."""
        if self._project is None:
            return
        try:
            self._service.reset_override(self._project, field)
            self.project_updated.emit()
            self.status_message.emit(f"{field} override reset.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to reset override")
            self.error_message.emit(f"Could not reset override:\n{exc}")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def available_statuses(self) -> tuple:
        return PROJECT_STATUSES

    def set_status(self, status: str) -> None:
        """Set the project status and persist."""
        if self._project is None:
            return
        try:
            self._service.set_status(self._project, status)
            self.project_updated.emit()
            self.status_message.emit(f"Status set to {status}.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to set status")
            self.error_message.emit(f"Could not set status:\n{exc}")

    # ------------------------------------------------------------------
    # Mockup generation (worker thread)
    # ------------------------------------------------------------------
    def generate_mockup(self, scene_template: str) -> None:
        """Generate artwork + physical mockup for the selected concept."""
        if self._project is None:
            self.error_message.emit("Open a project first.")
            return
        if self.is_generating:
            return
        if not scene_template:
            self.error_message.emit("Choose a scene template.")
            return

        thread = QThread()
        worker = MockupGenerationWorker(
            service=self._service,
            project_id=self._project.id,
            scene_template=scene_template,
            concept_id=self._project.selected_concept_id,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_generation_progress)
        worker.finished.connect(self._on_generation_finished)
        worker.failed.connect(self._on_generation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_generation_thread)

        self._thread = thread
        self._worker = worker
        self.generation_started.emit()
        self.status_message.emit("Generating mockup...")
        thread.start()

    def _on_generation_progress(self, percent: int, message: str) -> None:
        self.progress_changed.emit(percent, message)
        self.status_message.emit(message)

    def _on_generation_finished(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        project_id = data.get("project_id")
        if project_id and self._project is not None and self._project.id == project_id:
            try:
                self._project = self._service.open_project(project_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not reload project after generation: %s", exc)
        self.artifacts_changed.emit()
        self.project_updated.emit()
        self.generation_finished.emit()
        self.status_message.emit("✓ Mockup generated.")

    def _on_generation_failed(self, error: str) -> None:
        logger.error("Mockup generation failed: %s", error)
        self.generation_finished.emit()
        self.error_message.emit(f"Mockup generation failed:\n{error}")

    def _cleanup_generation_thread(self) -> None:
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(3000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def refresh(self) -> None:
        """Emit project_updated so open views re-render from current state."""
        self.project_updated.emit()

    # ------------------------------------------------------------------
    # File actions
    # ------------------------------------------------------------------
    def open_file(self, path: str) -> None:
        """Open an artifact/image in the system default viewer."""
        if not path or not os.path.isfile(path):
            self.error_message.emit("File no longer exists.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:  # noqa: BLE001
            logger.warning("Could not open file: %s", exc)
            self.error_message.emit(f"Could not open file:\n{exc}")

    def open_folder(self, path: str) -> None:
        """Open a folder in the system file manager."""
        folder = path or (self._project.root_dir if self._project else "")
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