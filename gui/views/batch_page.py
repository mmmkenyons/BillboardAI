"""Prospect batch mockup generation page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class BatchPage(QWidget):
    """Minimal Sprint 5J batch generation view."""

    queue_requested = Signal(list, dict)
    run_requested = Signal(list)
    open_project_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._row_ids: list[str] = []
        layout = QVBoxLayout(self)
        label = QLabel("Batch Mockups", self)
        label.setObjectName("previewHeading")
        layout.addWidget(label)

        self.prospect_table = QTableWidget(0, 5, self)
        self.prospect_table.setHorizontalHeaderLabels(["Select", "Company", "Website", "Template", "Eligibility"])
        layout.addWidget(self.prospect_table)

        actions = QHBoxLayout()
        self.queue_button = QPushButton("Queue Selected", self)
        self.queue_button.clicked.connect(self._emit_queue)
        actions.addWidget(self.queue_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        jobs_label = QLabel("Generation Jobs", self)
        jobs_label.setObjectName("previewHeading")
        layout.addWidget(jobs_label)

        self.jobs_table = QTableWidget(0, 4, self)
        self.jobs_table.setHorizontalHeaderLabels(["Company", "Template", "Status", "Result"])
        layout.addWidget(self.jobs_table)

        self.run_button = QPushButton("Run Queue", self)
        self.run_button.clicked.connect(self._emit_run)
        layout.addWidget(self.run_button)

        self.open_project_button = QPushButton("Open Selected Project", self)
        self.open_project_button.clicked.connect(self._emit_open_project)
        layout.addWidget(self.open_project_button)

        self.message_label = QLabel("", self)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

    def set_controller(self, controller: object) -> None:
        self._controller = controller
        if hasattr(controller, "prospects_changed"):
            controller.prospects_changed.connect(self.set_prospects)
        if hasattr(controller, "jobs_changed"):
            controller.jobs_changed.connect(self.set_jobs)
        if hasattr(controller, "status_message"):
            controller.status_message.connect(self.show_status)
        if hasattr(controller, "error_message"):
            controller.error_message.connect(self.show_error)
        if hasattr(controller, "running_changed"):
            controller.running_changed.connect(self.set_running)
        if hasattr(controller, "refresh"):
            controller.refresh()

    def set_prospects(self, rows: list[dict]) -> None:
        self.prospect_table.setRowCount(0)
        self._row_ids = []
        for row_data in rows:
            row = self.prospect_table.rowCount()
            self.prospect_table.insertRow(row)
            prospect_id = str(row_data.get("prospect_id") or "")
            self._row_ids.append(prospect_id)

            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(Qt.CheckState.Unchecked)
            select_item.setData(Qt.ItemDataRole.UserRole, prospect_id)
            self.prospect_table.setItem(row, 0, select_item)

            self.prospect_table.setItem(row, 1, QTableWidgetItem(str(row_data.get("company_name") or "")))
            self.prospect_table.setItem(row, 2, QTableWidgetItem(str(row_data.get("website") or "")))

            combo = QComboBox(self.prospect_table)
            combo.addItem("Choose template", "")
            for template in row_data.get("template_options", []):
                combo.addItem(template.title(), template)
            resolved = str(row_data.get("resolved_template") or "")
            if resolved:
                idx = combo.findData(resolved)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.prospect_table.setCellWidget(row, 3, combo)
            self.prospect_table.setItem(row, 4, QTableWidgetItem(str(row_data.get("eligibility") or "")))

    def set_jobs(self, rows: list[dict]) -> None:
        self.jobs_table.setRowCount(0)
        for row_data in rows:
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            self.jobs_table.setItem(row, 0, QTableWidgetItem(str(row_data.get("company_name") or "")))
            self.jobs_table.setItem(row, 1, QTableWidgetItem(str(row_data.get("template") or "")))
            self.jobs_table.setItem(row, 2, QTableWidgetItem(str(row_data.get("status") or "")))
            self.jobs_table.setItem(row, 3, QTableWidgetItem(str(row_data.get("result") or "")))

    def show_status(self, message: str) -> None:
        self.message_label.setText(message)

    def show_error(self, message: str) -> None:
        self.message_label.setText(message)

    def set_running(self, running: bool) -> None:
        self.queue_button.setEnabled(not running)
        self.run_button.setEnabled(not running)
        self.open_project_button.setEnabled(not running)

    def selected_prospect_ids(self) -> list[str]:
        selected: list[str] = []
        for row in range(self.prospect_table.rowCount()):
            item = self.prospect_table.item(row, 0)
            if item is None:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                prospect_id = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(prospect_id, str) and prospect_id:
                    selected.append(prospect_id)
        return selected

    def selected_templates(self) -> dict[str, str]:
        templates: dict[str, str] = {}
        for row in range(self.prospect_table.rowCount()):
            item = self.prospect_table.item(row, 0)
            combo = self.prospect_table.cellWidget(row, 3)
            if item is None or combo is None or item.checkState() != Qt.CheckState.Checked:
                continue
            prospect_id = item.data(Qt.ItemDataRole.UserRole)
            template = combo.currentData() if hasattr(combo, "currentData") else ""
            if isinstance(prospect_id, str) and isinstance(template, str) and template:
                templates[prospect_id] = template
        return templates

    def _emit_queue(self) -> None:
        self.queue_requested.emit(self.selected_prospect_ids(), self.selected_templates())

    def _emit_run(self) -> None:
        self.run_requested.emit([])

    def _emit_open_project(self) -> None:
        selected = self.selected_prospect_ids()
        if not selected:
            self.show_error("Select a prospect first.")
            return
        self.open_project_requested.emit(selected[0])