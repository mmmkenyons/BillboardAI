"""Progress bar panel widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

_STAGE_ICONS = {
    "start": "🚀 Starting...",
    "scrape": "🌐 Scraping Website",
    "assets": "🖼 Downloading Assets",
    "analyze": "🧠 Analyzing Brand",
    "copy": "🧠 Generating Copy",
    "render": "🎨 Rendering Mockup",
    "save": "💾 Saving Image",
    "done": "✓ Complete",
}


class ProgressPanel(QWidget):
    """Progress bar section with smooth animation and a stage label."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._animation: QPropertyAnimation | None = None
        self._build_ui()
        self.reset()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        self.stage_label = QLabel("", self)
        self.stage_label.setObjectName("stageLabel")
        self.stage_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stage_label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_progress(self, percent: int, message: str, stage: str = "") -> None:
        """Animate the progress bar to ``percent`` and update the stage label."""
        self._animate_to(percent)
        self.stage_label.setText(_STAGE_ICONS.get(stage, message))

    def reset(self) -> None:
        """Reset the progress bar and stage label."""
        self._stop_animation()
        self.progress_bar.setValue(0)
        self.stage_label.setText("")

    def _animate_to(self, target: int) -> None:
        self._stop_animation()
        animation = QPropertyAnimation(self.progress_bar, b"value", self)
        animation.setDuration(300)
        animation.setStartValue(self.progress_bar.value())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._animation = animation

    def _stop_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None