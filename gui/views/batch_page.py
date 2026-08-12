"""Prospect batch mockup generation page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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

    COL_SELECT = 0
    COL_COMPANY = 1
    COL_WEBSITE = 2
    COL_TEMPLATE = 3
    COL_OPPORTUNITY = 4
    COL_ELIGIBILITY = 5
    COL_EXPORT_STATUS = 6

    JOB_COL_COMPANY = 0
    JOB_COL_TEMPLATE = 1
    JOB_COL_OPPORTUNITY = 2
    JOB_COL_STATUS = 3
    JOB_COL_RESULT = 4

    queue_requested = Signal(list, dict, dict)
    run_requested = Signal(list)
    open_project_requested = Signal(str)
    export_requested = Signal(list, str)
    package_requested = Signal(list, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._bound_controller = None
        self._row_ids: list[str] = []
        layout = QVBoxLayout(self)
        label = QLabel("Batch Mockups", self)
        label.setObjectName("previewHeading")
        layout.addWidget(label)

        self.prospect_table = QTableWidget(0, 7, self)
        self.prospect_table.setHorizontalHeaderLabels(["Select", "Company", "Website", "Template", "Opportunity", "Eligibility", "Export"])
        layout.addWidget(self.prospect_table)

        actions = QHBoxLayout()
        self.queue_button = QPushButton("Queue Selected", self)
        self.queue_button.clicked.connect(self._emit_queue)
        actions.addWidget(self.queue_button)
        self.export_button = QPushButton("Export Campaign CSV", self)
        self.export_button.clicked.connect(self._export_campaign_csv)
        actions.addWidget(self.export_button)
        self.package_button = QPushButton("Build Campaign Package", self)
        self.package_button.clicked.connect(self._build_campaign_package)
        actions.addWidget(self.package_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        jobs_label = QLabel("Generation Jobs", self)
        jobs_label.setObjectName("previewHeading")
        layout.addWidget(jobs_label)

        self.jobs_table = QTableWidget(0, 5, self)
        self.jobs_table.setHorizontalHeaderLabels(["Company", "Template", "Opportunity", "Status", "Result"])
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
        if controller is self._bound_controller:
            return
        self._controller = controller
        self._bound_controller = controller
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
        if hasattr(controller, "export_preview_changed"):
            controller.export_preview_changed.connect(self._consume_export_preview)
        if hasattr(controller, "queue_selected"):
            self.queue_requested.connect(controller.queue_selected)
        if hasattr(controller, "run_queue"):
            self.run_requested.connect(lambda _ignored: controller.run_queue())
        if hasattr(controller, "open_project_for_prospect"):
            self.open_project_requested.connect(controller.open_project_for_prospect)
        if hasattr(controller, "export_campaign_csv"):
            self.export_requested.connect(controller.export_campaign_csv)
        if hasattr(controller, "build_campaign_package"):
            self.package_requested.connect(controller.build_campaign_package)
        if hasattr(controller, "refresh"):
            controller.refresh()

    def set_prospects(self, rows: list[dict]) -> None:
        selected_before = set(self.selected_prospect_ids())
        self.prospect_table.setRowCount(0)
        self._row_ids = []
        for row_data in rows:
            row = self.prospect_table.rowCount()
            self.prospect_table.insertRow(row)
            prospect_id = str(row_data.get("prospect_id") or "")
            self._row_ids.append(prospect_id)

            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(
                Qt.CheckState.Checked
                if prospect_id in selected_before
                else Qt.CheckState.Unchecked
            )
            select_item.setData(Qt.ItemDataRole.UserRole, prospect_id)
            self.prospect_table.setItem(row, self.COL_SELECT, select_item)

            self.prospect_table.setItem(row, self.COL_COMPANY, QTableWidgetItem(str(row_data.get("company_name") or "")))
            self.prospect_table.setItem(row, self.COL_WEBSITE, QTableWidgetItem(str(row_data.get("website") or "")))

            combo = QComboBox(self.prospect_table)
            combo.addItem("Choose template", "")
            for template in row_data.get("template_options", []):
                combo.addItem(template.title(), template)
            resolved = str(row_data.get("resolved_template") or "")
            if resolved:
                idx = combo.findData(resolved)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.prospect_table.setCellWidget(row, self.COL_TEMPLATE, combo)
            self.prospect_table.setItem(row, self.COL_OPPORTUNITY, QTableWidgetItem(str(row_data.get("opportunity") or "Generic")))
            self.prospect_table.setItem(row, self.COL_ELIGIBILITY, QTableWidgetItem(str(row_data.get("eligibility") or "")))
            self.prospect_table.setItem(row, self.COL_EXPORT_STATUS, QTableWidgetItem(str(row_data.get("export_status") or "")))

    def set_jobs(self, rows: list[dict]) -> None:
        self.jobs_table.setRowCount(0)
        for row_data in rows:
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            self.jobs_table.setItem(row, self.JOB_COL_COMPANY, QTableWidgetItem(str(row_data.get("company_name") or "")))
            self.jobs_table.setItem(row, self.JOB_COL_TEMPLATE, QTableWidgetItem(str(row_data.get("template") or "")))
            self.jobs_table.setItem(row, self.JOB_COL_OPPORTUNITY, QTableWidgetItem(str(row_data.get("opportunity") or "Generic")))
            self.jobs_table.setItem(row, self.JOB_COL_STATUS, QTableWidgetItem(str(row_data.get("status") or "")))
            self.jobs_table.setItem(row, self.JOB_COL_RESULT, QTableWidgetItem(str(row_data.get("result") or "")))

    def show_status(self, message: str) -> None:
        self.message_label.setText(message)

    def show_error(self, message: str) -> None:
        self.message_label.setText(message)

    def set_running(self, running: bool) -> None:
        self.queue_button.setEnabled(not running)
        self.run_button.setEnabled(not running)
        self.open_project_button.setEnabled(not running)
        self.export_button.setEnabled(not running)
        self.package_button.setEnabled(not running)

    def _consume_export_preview(self, _rows: list[dict]) -> None:
        # Preview is currently summarized directly in the prospect table's Export column.
        return

    def selected_prospect_ids(self) -> list[str]:
        selected: list[str] = []
        for row in range(self.prospect_table.rowCount()):
            item = self.prospect_table.item(row, self.COL_SELECT)
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
            item = self.prospect_table.item(row, self.COL_SELECT)
            combo = self.prospect_table.cellWidget(row, self.COL_TEMPLATE)
            if item is None or combo is None or item.checkState() != Qt.CheckState.Checked:
                continue
            prospect_id = item.data(Qt.ItemDataRole.UserRole)
            template = combo.currentData() if hasattr(combo, "currentData") else ""
            if isinstance(prospect_id, str) and isinstance(template, str) and template:
                templates[prospect_id] = template
        return templates

    def _emit_queue(self) -> None:
        self.queue_requested.emit(self.selected_prospect_ids(), self.selected_templates(), {})

    def _emit_run(self) -> None:
        self.run_requested.emit([])

    def _emit_open_project(self) -> None:
        selected = self.selected_prospect_ids()
        if not selected:
            self.show_error("Select a prospect first.")
            return
        self.open_project_requested.emit(selected[0])

    def _export_campaign_csv(self) -> None:
        if self._controller is None:
            self.show_error("No batch controller attached.")
            return
        selected = self.selected_prospect_ids()
        if not selected:
            self.show_error("Select at least one prospect to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Campaign CSV",
            "campaign_export.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            self.show_status("Campaign export cancelled.")
            return
        try:
            self.export_requested.emit(selected, path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Campaign export failed: {exc}")

    def _build_campaign_package(self) -> None:
        if self._controller is None:
            self.show_error("No batch controller attached.")
            return
        selected = self.selected_prospect_ids()
        if not selected:
            self.show_error("Select at least one prospect to package.")
            return
        destination = QFileDialog.getExistingDirectory(self, "Choose Campaign Package Destination")
        if not destination:
            self.show_status("Campaign package cancelled.")
            return
        campaign_name = self._default_campaign_name(selected)
        try:
            result = self._controller.build_campaign_package(selected, destination, campaign_name)
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"Campaign package failed: {exc}")
            return
        if not getattr(result, "success", False):
            self.show_error(result.message)
            return
        self.show_status(result.message)

    def _default_campaign_name(self, selected: list[str]) -> str:
        companies: list[str] = []
        for row in range(self.prospect_table.rowCount()):
            item = self.prospect_table.item(row, self.COL_SELECT)
            if item is None:
                continue
            prospect_id = item.data(Qt.ItemDataRole.UserRole)
            if prospect_id not in selected:
                continue
            company_item = self.prospect_table.item(row, self.COL_COMPANY)
            if company_item is not None and company_item.text():
                companies.append(company_item.text())
        if not companies:
            return "campaign_package"
        if len(companies) == 1:
            return companies[0]
        return f"{companies[0]}_{len(companies)}_prospects"