"""Logo header widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class Header(QWidget):
    """BillboardAI logo banner shown at the top of the window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title = QLabel("BillboardAI", self)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title.setObjectName("logoTitle")
        title.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))

        subtitle = QLabel("AI-Powered Billboard Mockup Generator", self)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        subtitle.setObjectName("logoSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)