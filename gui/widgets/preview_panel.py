"""Image preview panel widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.models.mockup_concept import MockupConcept
from gui.widgets.quality_badge import QualityBadge

_PLACEHOLDER_TEXT = "No mockup generated yet."


class PreviewPanel(QFrame):
    """Panel that displays the rendered billboard image preview.

    Emits signals for the action buttons beneath the preview.
    """

    open_image_requested = Signal()
    open_folder_requested = Signal()
    copy_path_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(320)

        self._pixmap: QPixmap | None = None
        self._image_path: str = ""
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        heading = QLabel("Generated Mockup", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        # Placeholder area for the rendered billboard image.
        self.preview_label = QLabel(_PLACEHOLDER_TEXT, self)
        self.preview_label.setObjectName("previewPlaceholder")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(260)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_label.setWordWrap(True)

        layout.addWidget(self.preview_label, stretch=1)

        # Action buttons beneath the preview.
        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.open_image_button = QPushButton("Open Image", self)
        self.open_image_button.clicked.connect(self.open_image_requested.emit)
        button_row.addWidget(self.open_image_button)

        self.open_folder_button = QPushButton("Open Folder", self)
        self.open_folder_button.clicked.connect(self.open_folder_requested.emit)
        button_row.addWidget(self.open_folder_button)

        self.copy_path_button = QPushButton("Copy File Path", self)
        self.copy_path_button.clicked.connect(self.copy_path_requested.emit)
        button_row.addWidget(self.copy_path_button)

        button_row.addStretch(1)
        layout.addLayout(button_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_image(self, path: str) -> None:
        """Load and display the image at ``path``, scaled proportionally."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.clear()
            return
        self._pixmap = pixmap
        self._image_path = path
        self.preview_label.setObjectName("previewImage")
        self.preview_label.setWordWrap(False)
        self._update_scaled_pixmap()
        self._set_buttons_enabled(True)

    def set_concept(self, concept: MockupConcept) -> None:
        """Display the image from a MockupConcept.

        Uses the concept's ``image_path`` to load the pixmap.
        """
        self.set_image(concept.image_path)

    def clear(self) -> None:
        """Restore the placeholder text and disable action buttons."""
        self._pixmap = None
        self._image_path = ""
        self.preview_label.setObjectName("previewPlaceholder")
        self.preview_label.setWordWrap(True)
        self.preview_label.setText(_PLACEHOLDER_TEXT)
        self._set_buttons_enabled(False)

    def image_path(self) -> str:
        """Return the currently displayed image path (empty if none)."""
        return self._image_path

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.open_image_button.setEnabled(enabled)
        self.open_folder_button.setEnabled(enabled)
        self.copy_path_button.setEnabled(enabled)

    def _update_scaled_pixmap(self) -> None:
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_scaled_pixmap()
