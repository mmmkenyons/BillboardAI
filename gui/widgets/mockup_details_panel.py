"""Mockup details panel widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gui.models.mockup_result import MockupResult
from gui.widgets.quality_badge import QualityBadge

_EMPTY_TEXT = "Generate your first billboard mockup."
_NOT_AVAILABLE = "Not Available"


class MockupDetailsPanel(QFrame):
    """Displays metadata about the generated mockup.

    Empty fields are hidden gracefully; missing values show
    "Not Available".
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailsPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        heading = QLabel("Mockup Details", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        self.empty_label = QLabel(_EMPTY_TEXT, self)
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.form = QFormLayout()
        self.form.setSpacing(8)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.company_value = QLabel(self)
        self.quality_badge = QualityBadge(self)
        self.headline_value = QLabel(self)
        self.cta_value = QLabel(self)
        self.elapsed_value = QLabel(self)

        self.form.addRow("Company", self.company_value)
        self.form.addRow("Quality", self.quality_badge)
        self.form.addRow("Headline", self.headline_value)
        self.form.addRow("CTA", self.cta_value)
        self.form.addRow("Elapsed", self.elapsed_value)

        layout.addLayout(self.form)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_result(self, result: MockupResult) -> None:
        """Populate the panel from a :class:`MockupResult`."""
        self.empty_label.hide()
        self.form.setRowVisible(0, bool(result.company_name))
        self.form.setRowVisible(1, result.quality_score > 0)
        self.form.setRowVisible(2, bool(result.headline))
        self.form.setRowVisible(3, bool(result.cta))
        self.form.setRowVisible(4, result.elapsed_time > 0)

        self.company_value.setText(result.company_name or _NOT_AVAILABLE)
        self.quality_badge.set_score(result.quality_score)
        self.headline_value.setText(result.headline or _NOT_AVAILABLE)
        self.cta_value.setText(result.cta or _NOT_AVAILABLE)
        self.elapsed_value.setText(f"{result.elapsed_time:.1f} seconds")

    def clear(self) -> None:
        """Reset to the empty state."""
        self.empty_label.show()
        for row in range(self.form.rowCount()):
            self.form.setRowVisible(row, False)