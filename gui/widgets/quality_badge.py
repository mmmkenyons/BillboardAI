"""Quality score badge widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget


class QualityBadge(QLabel):
    """Displays a colored quality status driven by the quality score."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("qualityBadge")
        self.set_score(0)

    def set_score(self, score: float) -> None:
        """Update the badge based on the quality score value."""
        if score >= 95:
            self.setText("🟢 Excellent")
            self.setProperty("qualityLevel", "excellent")
        elif score >= 80:
            self.setText("🟡 Good")
            self.setProperty("qualityLevel", "good")
        else:
            self.setText("🟠 Needs Improvement")
            self.setProperty("qualityLevel", "needs_improvement")
        # Re-polish so the property-driven stylesheet applies.
        self.style().unpolish(self)
        self.style().polish(self)