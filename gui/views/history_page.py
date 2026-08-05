"""History page for the BillboardAI GUI (placeholder)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class HistoryPage(QWidget):
    """Placeholder history view.

    Hidden for now; will be populated when generation history is added.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel("History", self)
        label.setObjectName("previewHeading")
        layout.addWidget(label)
        layout.addStretch(1)