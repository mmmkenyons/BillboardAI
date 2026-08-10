"""Artifact card widget for the Sprint 3B ARTWORK / MOCKUPS tab.

Displays one :class:`gui.models.project_artifact.ProjectArtifact` with a safe
thumbnail, artifact type, concept association, scene template, composition
family, dimensions, and created date. Emits ``open_image`` / ``open_folder``
signals for the controller to handle.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.models.project_artifact import ProjectArtifact
from gui.widgets.thumbnail_loader import ThumbnailLabel

_THUMB_W = 260
_THUMB_H = 130


class ArtifactCard(QFrame):
    """A card showing one generated artifact with its metadata."""

    open_image = Signal(str)  # absolute path
    open_folder = Signal(str)  # folder path

    def __init__(
        self,
        artifact: ProjectArtifact,
        image_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.artifact = artifact
        self.setObjectName("artifactCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._image_path = image_path
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Thumbnail.
        thumb = ThumbnailLabel(_THUMB_W, _THUMB_H, self)
        thumb.set_image_path(self._image_path)
        layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Type + scene.
        type_label = QLabel(
            str(self.artifact.artifact_type or "artifact").upper(), self
        )
        type_label.setObjectName("artifactType")
        layout.addWidget(type_label)

        # Concept / scene / composition.
        concept = QLabel(f"Concept: {self.artifact.concept_id or '—'}", self)
        concept.setObjectName("artifactMeta")
        layout.addWidget(concept)

        scene = QLabel(f"Scene: {self.artifact.scene_template or '—'}", self)
        scene.setObjectName("artifactMeta")
        layout.addWidget(scene)

        family = QLabel(
            f"Composition: {self.artifact.composition_family or '—'}", self
        )
        family.setObjectName("artifactMeta")
        layout.addWidget(family)

        dims = QLabel(
            f"Size: {self.artifact.width or '?'} × {self.artifact.height or '?'} px",
            self,
        )
        dims.setObjectName("artifactMeta")
        layout.addWidget(dims)

        created = QLabel(
            f"Created: {self.artifact.created_at.strftime('%Y-%m-%d %H:%M')}", self
        )
        created.setObjectName("artifactMeta")
        layout.addWidget(created)

        # Actions.
        buttons = QHBoxLayout()
        open_image_btn = QPushButton("Open Image", self)
        open_image_btn.setObjectName("secondaryButton")
        open_image_btn.clicked.connect(
            lambda: self.open_image.emit(self._image_path)
        )
        open_folder_btn = QPushButton("Open Folder", self)
        open_folder_btn.setObjectName("secondaryButton")
        open_folder_btn.clicked.connect(
            lambda: self.open_folder.emit(
                self._image_path.rsplit("/", 1)[0] if self._image_path else ""
            )
        )
        buttons.addWidget(open_image_btn)
        buttons.addWidget(open_folder_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)