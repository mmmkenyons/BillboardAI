"""Background worker for Sprint 3B mockup generation (AdConcept -> scene mockup).

Runs the Qt-free :class:`~gui.services.project_workspace.ProjectWorkspaceService`
generation pipeline off the GUI thread. The worker is a ``QObject`` moved to a
``QThread``; it never creates QObject children with GUI parents and only emits
signals (queued to the GUI thread), so no cross-thread Qt errors occur.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from gui.services.project_workspace import ProjectWorkspaceService

logger = logging.getLogger(__name__)


class MockupGenerationWorker(QObject):
    """Generate artwork + physical mockup for a concept in a worker thread."""

    progress = Signal(int, str)  # percent, message
    finished = Signal(object)  # list[dict] artifact metadata
    failed = Signal(str)  # error message

    def __init__(
        self,
        service: ProjectWorkspaceService,
        project_id: str,
        scene_template: str,
        concept_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._project_id = project_id
        self._scene_template = scene_template
        self._concept_id = concept_id

    def run(self) -> None:
        """Execute the mockup generation pipeline (worker thread)."""
        try:
            self.progress.emit(10, "Loading project...")
            project = self._service.open_project(self._project_id)
            self.progress.emit(40, "Rendering artwork...")
            artifacts = self._service.generate_mockup(
                project,
                self._scene_template,
                concept_id=self._concept_id,
            )
            self.progress.emit(90, "Finalizing mockup...")
            # Reload so the controller sees the freshly persisted state.
            project = self._service.open_project(self._project_id)
            self.progress.emit(100, "Mockup generated")
            self.finished.emit(
                {
                    "project_id": project.id,
                    "artifacts": [a.to_dict() for a in project.artifacts],
                    "new_artifacts": [a.to_dict() for a in artifacts],
                }
            )
        except Exception as exc:  # noqa: BLE001 - never crash the GUI
            logger.exception("Mockup generation failed")
            self.failed.emit(str(exc))