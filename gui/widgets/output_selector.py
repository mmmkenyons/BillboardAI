"""Output folder selector widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from gui.models.app_settings import DEFAULT_OUTPUT_FOLDER


class OutputSelector(QWidget):
    """Read-only output folder field with a Browse button.

    The widget does not open a file dialog itself. Clicking Browse emits
    :attr:`browse_requested`; the owning controller/page handles the dialog
    and updates this widget via :meth:`set_folder`.
    """

    browse_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.output_folder_input = QLineEdit(self)
        self.output_folder_input.setReadOnly(True)
        self.output_folder_input.setPlaceholderText("Choose an output folder")
        self.output_folder_input.setText(DEFAULT_OUTPUT_FOLDER)

        browse_button = QPushButton("Browse…", self)
        browse_button.setObjectName("browseButton")
        browse_button.clicked.connect(self.browse_requested.emit)
        browse_button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.output_folder_input, stretch=1)
        layout.addWidget(browse_button)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def folder(self) -> str:
        """Return the currently selected output folder."""
        return self.output_folder_input.text().strip()

    def set_folder(self, folder: str) -> None:
        """Update the displayed output folder."""
        self.output_folder_input.setText(folder)