"""Image preview panel widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_PLACEHOLDER_TEXT = "No preview yet — generated mockups will appear here."


class PreviewPanel(QFrame):
    """Panel that displays the rendered billboard image preview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(320)

        self._pixmap: QPixmap | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        heading = QLabel("Preview", self)
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
        self.preview_label.setObjectName("previewImage")
        self.preview_label.setWordWrap(False)
        self._update_scaled_pixmap()

    def clear(self) -> None:
        """Restore the placeholder text."""
        self._pixmap = None
        self.preview_label.setObjectName("previewPlaceholder")
        self.preview_label.setWordWrap(True)
        self.preview_label.setText(_PLACEHOLDER_TEXT)

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