"""Minimal Smartlead preflight workspace."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QLineEdit,
)

from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_DRY_RUN,
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_TARGET_MODE_CREATE_DRAFT,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadPublishTarget,
)


class SmartleadHandoffPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._rows: list[dict] = []
        self._campaigns: list[object] = []
        self._handoff_directory: str = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Smartlead Preflight", self))

        connection_row = QHBoxLayout()
        self.api_status_label = QLabel("Smartlead API key: Not configured", self)
        self.test_connection_button = QPushButton("Test Connection", self)
        self.refresh_campaigns_button = QPushButton("Refresh Campaigns", self)
        connection_row.addWidget(self.api_status_label)
        connection_row.addStretch(1)
        connection_row.addWidget(self.test_connection_button)
        connection_row.addWidget(self.refresh_campaigns_button)
        layout.addLayout(connection_row)

        publish_row = QHBoxLayout()
        self.target_mode_combo = QComboBox(self)
        self.target_mode_combo.addItems(["Existing Campaign", "Create Draft Campaign"])
        self.campaign_combo = QComboBox(self)
        self.create_name_edit = QLineEdit(self)
        self.create_name_edit.setPlaceholderText("New draft campaign name")
        self.live_checkbox = QCheckBox("Enable live Smartlead writes", self)
        self.live_checkbox.setChecked(False)
        self.publish_button = QPushButton("Upload Approved Leads", self)
        publish_row.addWidget(QLabel("Target:", self))
        publish_row.addWidget(self.target_mode_combo)
        publish_row.addWidget(self.campaign_combo)
        publish_row.addWidget(self.create_name_edit)
        publish_row.addWidget(self.live_checkbox)
        publish_row.addWidget(self.publish_button)
        layout.addLayout(publish_row)

        top = QHBoxLayout()
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems(["All", "Ready", "Warning", "Blocked", "Conflict"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        top.addWidget(QLabel("Filter:", self))
        top.addWidget(self.filter_combo)
        top.addStretch(1)
        self.summary_label = QLabel("No preflight run yet.", self)
        top.addWidget(self.summary_label)
        layout.addLayout(top)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Prospect", "Company", "Email", "Status"])
        self.table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self.table)

        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

    def set_controller(self, controller: object) -> None:
        if controller is self._controller:
            return
        self._controller = controller
        if hasattr(controller, "summary_changed"):
            controller.summary_changed.connect(self.set_summary)
        if hasattr(controller, "rows_changed"):
            controller.rows_changed.connect(self.set_rows)
        if hasattr(controller, "status_message"):
            controller.status_message.connect(self.show_status)
        if hasattr(controller, "error_message"):
            controller.error_message.connect(self.show_status)
        if hasattr(controller, "connection_changed"):
            controller.connection_changed.connect(self.set_connection_status)
        if hasattr(controller, "campaigns_changed"):
            controller.campaigns_changed.connect(self.set_campaigns)
        if hasattr(controller, "publish_result_changed"):
            controller.publish_result_changed.connect(self.show_publish_result)
        self.test_connection_button.clicked.connect(self._on_test_connection)
        self.refresh_campaigns_button.clicked.connect(self._on_refresh_campaigns)
        self.publish_button.clicked.connect(self._on_publish)
        self.target_mode_combo.currentTextChanged.connect(self._sync_target_mode)
        self._sync_target_mode(self.target_mode_combo.currentText())

    def set_summary(self, summary: object) -> None:
        self._handoff_directory = str(getattr(summary, "handoff_directory", "") or self._handoff_directory)
        self.summary_label.setText(
            f"Approved: {getattr(summary, 'total_approved_rows', 0)} | "
            f"Ready: {getattr(summary, 'ready', 0)} | "
            f"Warning: {getattr(summary, 'warnings', 0)} | "
            f"Blocked: {getattr(summary, 'blocked', 0)} | "
            f"Conflict: {getattr(summary, 'conflicts', 0)}"
        )

    def set_rows(self, rows: list[dict]) -> None:
        self._rows = list(rows or [])
        self._render_rows(self._rows)

    def set_connection_status(self, result: object) -> None:
        configured = "Configured" if getattr(result, "status", "") != "NOT_CONFIGURED" else "Not configured"
        self.api_status_label.setText(f"Smartlead API key: {configured} | Connection: {getattr(result, 'message', '')}")

    def set_campaigns(self, campaigns: list[object]) -> None:
        self._campaigns = list(campaigns or [])
        current = self.campaign_combo.currentData()
        self.campaign_combo.blockSignals(True)
        self.campaign_combo.clear()
        for campaign in self._campaigns:
            label = f"{getattr(campaign, 'name', '')} ({getattr(campaign, 'status', '')})"
            self.campaign_combo.addItem(label, getattr(campaign, 'campaign_id', ''))
        if current:
            index = self.campaign_combo.findData(current)
            if index >= 0:
                self.campaign_combo.setCurrentIndex(index)
        self.campaign_combo.blockSignals(False)

    def show_publish_result(self, result: object) -> None:
        lines = [str(getattr(result, "message", ""))]
        if getattr(result, "campaign_name", ""):
            lines.append(f"Campaign: {getattr(result, 'campaign_name', '')} ({getattr(result, 'campaign_id', '')})")
        lines.append(f"Mode: {getattr(result, 'mode', '')}")
        lines.append(f"Eligible: {getattr(result, 'eligible', 0)} | Succeeded: {getattr(result, 'succeeded', 0)} | Skipped: {getattr(result, 'skipped', 0)} | Failed: {getattr(result, 'failed', 0)}")
        self.detail.setPlainText("\n".join(lines))

    def show_status(self, message: str) -> None:
        if message:
            self.detail.setPlainText(str(message))

    def set_handoff_directory(self, path: str) -> None:
        self._handoff_directory = str(path or "")

    def _apply_filter(self, value: str) -> None:
        status = str(value or "All").strip().upper()
        if status == "ALL":
            self._render_rows(self._rows)
            return
        self._render_rows([row for row in self._rows if str(row.get("status") or "").upper() == status])

    def _render_rows(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(str(row.get("prospect_id") or "")))
            self.table.setItem(index, 1, QTableWidgetItem(str(row.get("company") or "")))
            self.table.setItem(index, 2, QTableWidgetItem(str(row.get("email") or "")))
            self.table.setItem(index, 3, QTableWidgetItem(str(row.get("status") or "")))

    def _show_selected(self) -> None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= self.table.rowCount():
            return
        prospect_id_item = self.table.item(row_index, 0)
        prospect_id = prospect_id_item.text() if prospect_id_item is not None else ""
        payload = next((row for row in self._rows if str(row.get("prospect_id") or "") == prospect_id), None)
        if payload is None:
            return
        mapped = payload.get("mapped_fields") or {}
        lines = [
            f"Prospect: {payload.get('prospect_id', '')}",
            f"Status: {payload.get('status', '')}",
            f"Reason: {payload.get('reason', '')}",
            f"Warning: {payload.get('warning', '')}",
            "",
            "Mapped Fields:",
        ]
        for key, value in mapped.items():
            lines.append(f"{key}: {value}")
        self.detail.setPlainText("\n".join(lines))

    def _sync_target_mode(self, value: str) -> None:
        create_mode = str(value or "").strip().lower().startswith("create")
        self.campaign_combo.setEnabled(not create_mode)
        self.create_name_edit.setEnabled(create_mode)

    def _on_test_connection(self) -> None:
        if self._controller is not None and hasattr(self._controller, "test_connection"):
            self._controller.test_connection()

    def _on_refresh_campaigns(self) -> None:
        if self._controller is not None and hasattr(self._controller, "refresh_campaigns"):
            self._controller.refresh_campaigns()

    def _on_publish(self) -> None:
        if self._controller is None or not self._handoff_directory:
            return
        live = self.live_checkbox.isChecked()
        target = self._publish_target()
        mode = SMARTLEAD_PUBLISH_MODE_LIVE if live else SMARTLEAD_PUBLISH_MODE_DRY_RUN
        confirmed = True
        if live:
            message = self._confirmation_message(target, mode)
            confirmed = QMessageBox.question(self, "Confirm Smartlead Upload", message) == QMessageBox.StandardButton.Yes
        if hasattr(self._controller, "publish"):
            self._controller.publish(
                self._handoff_directory,
                target=target,
                mode=mode,
                live_enabled=live,
                confirmed=confirmed,
            )

    def _publish_target(self) -> SmartleadPublishTarget:
        create_mode = self.target_mode_combo.currentText().strip().lower().startswith("create")
        if create_mode:
            return SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_CREATE_DRAFT, create_name=self.create_name_edit.text().strip())
        return SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id=str(self.campaign_combo.currentData() or ""), campaign_name=self.campaign_combo.currentText().split(" (")[0])

    def _confirmation_message(self, target: SmartleadPublishTarget, mode: str) -> str:
        target_name = target.create_name if target.mode == SMARTLEAD_TARGET_MODE_CREATE_DRAFT else target.campaign_name
        eligible = len([row for row in self._rows if str(row.get("status") or "").upper() in {"READY", "WARNING"}])
        blocked = len([row for row in self._rows if str(row.get("status") or "").upper() in {"BLOCKED", "CONFLICT"}])
        return (
            f"Upload {eligible} approved leads to Smartlead campaign\n{target_name}?\n\n"
            f"Mode: {mode}\n"
            f"Blocked/Conflict rows excluded: {blocked}\n\n"
            "This uploads leads only. It does NOT start or launch the campaign."
        )
