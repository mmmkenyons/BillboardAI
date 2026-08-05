"""Image preview panel widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class PreviewPanel(QFrame):
    """Panel that displays the rendered billboard image preview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(320)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        heading = QLabel("Preview", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        # Placeholder area for the rendered billboard image.
        self.preview_label = QLabel(
            "No preview yet — generated mockups will appear here.", self
        )
        self.preview_label.setObjectName("previewPlaceholder")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(260)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_label.setWordWrap(True)

        layout.addWidget(self.preview_label, stretch=1)