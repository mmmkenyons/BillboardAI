"""Persistent presentation-only workflow navigation bar for Sprint 5V."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from gui.models.workflow_stage import WorkflowStageViewModel


class WorkflowBar(QFrame):
    stage_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowBar")
        self._buttons: dict[str, QPushButton] = {}
        self._detail_labels: dict[str, QLabel] = {}
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def set_stages(self, stages: list[WorkflowStageViewModel]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()
        self._detail_labels.clear()
        for stage in stages:
            card = QFrame(self)
            card.setProperty("stageState", stage.state.value)
            card.setProperty("stageCurrent", stage.current)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(8, 6, 8, 6)
            inner.setSpacing(2)
            button = QPushButton(stage.label, card)
            button.setCheckable(True)
            button.setChecked(stage.current)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, stage_id=stage.stage_id.value: self.stage_requested.emit(stage_id))
            detail = QLabel(self._detail_text(stage), card)
            detail.setWordWrap(False)
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            detail.setMinimumHeight(0)
            detail.setMaximumHeight(20)
            detail.setToolTip(detail.text())
            inner.addWidget(button)
            inner.addWidget(detail)
            self._layout.addWidget(card, 1)
            self._buttons[stage.stage_id.value] = button
            self._detail_labels[stage.stage_id.value] = detail

    def _detail_text(self, stage: WorkflowStageViewModel) -> str:
        parts = [stage.state.value.replace("_", " ").title()]
        if stage.count is not None:
            parts.append(str(stage.count))
        if stage.blocker_summary:
            parts.append(stage.blocker_summary)
        elif stage.recommended_action_label:
            parts.append(stage.recommended_action_label)
        return " • ".join(part for part in parts if part)
