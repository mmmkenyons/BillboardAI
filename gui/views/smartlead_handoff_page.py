"""Minimal Smartlead preflight workspace."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
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
from gui.services.workflow_presentation import format_blocker, format_status


class SmartleadHandoffPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._rows: list[dict] = []
        self._campaigns: list[object] = []
        self._handoff_directory: str = ""
        self._package_directory: str = ""
        self._last_launch_readiness = None
        self._last_activation_result = None
        self._pilot_runs: list[object] = []
        self._current_pilot_id: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll_area)

        content = QWidget(self.scroll_area)
        self.scroll_area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        preflight_box = self._section_box("Smartlead Preflight", content)
        preflight_layout = self._section_layout(preflight_box)

        connection_row = QHBoxLayout()
        connection_row.setSpacing(8)
        self.api_status_label = QLabel("Smartlead API key: Not configured", self)
        self.api_status_label.setWordWrap(True)
        self.test_connection_button = QPushButton("Test Connection", self)
        self.refresh_campaigns_button = QPushButton("Refresh Campaigns", self)
        connection_row.addWidget(self.api_status_label)
        connection_row.addStretch(1)
        connection_row.addWidget(self.test_connection_button)
        connection_row.addWidget(self.refresh_campaigns_button)
        preflight_layout.addLayout(connection_row)

        publish_grid = QGridLayout()
        publish_grid.setHorizontalSpacing(8)
        publish_grid.setVerticalSpacing(8)
        self.target_mode_combo = QComboBox(self)
        self.target_mode_combo.addItems(["Existing Campaign", "Create Draft Campaign"])
        self.campaign_combo = QComboBox(self)
        self.create_name_edit = QLineEdit(self)
        self.create_name_edit.setPlaceholderText("New draft campaign name")
        self.live_checkbox = QCheckBox("Enable live Smartlead writes", self)
        self.live_checkbox.setChecked(False)
        self.publish_button = QPushButton("Upload Approved Leads", self)
        publish_grid.addWidget(QLabel("Target:", self), 0, 0)
        publish_grid.addWidget(self.target_mode_combo, 0, 1)
        publish_grid.addWidget(self.campaign_combo, 0, 2)
        publish_grid.addWidget(self.create_name_edit, 1, 1, 1, 2)
        publish_grid.addWidget(self.live_checkbox, 2, 1)
        publish_grid.addWidget(self.publish_button, 2, 2)
        preflight_layout.addLayout(publish_grid)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems(["All", "Ready", "Warning", "Blocked", "Conflict"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        top.addWidget(QLabel("Filter:", self))
        top.addWidget(self.filter_combo)
        top.addStretch(1)
        self.summary_label = QLabel("No preflight run yet.", self)
        self.summary_label.setWordWrap(True)
        top.addWidget(self.summary_label)
        preflight_layout.addLayout(top)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Prospect", "Company", "Email", "Status"])
        self.table.itemSelectionChanged.connect(self._show_selected)
        preflight_layout.addWidget(self.table)

        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        preflight_layout.addWidget(self.detail)
        layout.addWidget(preflight_box)

        hosting_box = self._section_box("Hosted Mockups", content)
        hosting_layout = self._section_layout(hosting_box)

        hosting_row = QHBoxLayout()
        hosting_row.setSpacing(8)
        self.hosting_status_label = QLabel("Hosting: Not configured", self)
        self.hosting_status_label.setWordWrap(True)
        self.test_hosting_connection_button = QPushButton("Test Hosting Connection", self)
        self.hosting_dry_run_button = QPushButton("Hosting Dry Run", self)
        self.hosting_live_checkbox = QCheckBox("Enable live hosting", self)
        self.hosting_live_checkbox.setChecked(False)
        self.host_mockups_button = QPushButton("Host Approved Mockups", self)
        hosting_row.addWidget(self.hosting_status_label)
        hosting_row.addStretch(1)
        hosting_row.addWidget(self.test_hosting_connection_button)
        hosting_row.addWidget(self.hosting_dry_run_button)
        hosting_row.addWidget(self.hosting_live_checkbox)
        hosting_row.addWidget(self.host_mockups_button)
        hosting_layout.addLayout(hosting_row)
        self.hosting_summary_label = QLabel("No hosting run yet.", self)
        self.hosting_summary_label.setWordWrap(True)
        hosting_layout.addWidget(self.hosting_summary_label)
        layout.addWidget(hosting_box)
        sequence_box = self._section_box("Sequence Readiness", content)
        sequence_layout = self._section_layout(sequence_box)
        sequence_row = QGridLayout()
        sequence_row.setHorizontalSpacing(8)
        sequence_row.setVerticalSpacing(8)
        self.readiness_label = QLabel("No readiness audit yet.", self)
        self.readiness_label.setWordWrap(True)
        self.refresh_readiness_button = QPushButton("Refresh Readiness", self)
        self.prepare_live_checkbox = QCheckBox("Enable live sequence write", self)
        self.prepare_live_checkbox.setChecked(False)
        self.prepare_sequence_button = QPushButton("Prepare Sequence", self)
        self.sync_live_checkbox = QCheckBox("Sync URLs live", self)
        self.sync_live_checkbox.setChecked(False)
        self.sync_urls_button = QPushButton("Sync Hosted URLs to Leads", self)
        sequence_row.addWidget(self.readiness_label, 0, 0, 1, 3)
        sequence_row.addWidget(self.refresh_readiness_button, 1, 0)
        sequence_row.addWidget(self.prepare_live_checkbox, 1, 1)
        sequence_row.addWidget(self.prepare_sequence_button, 1, 2)
        sequence_row.addWidget(self.sync_live_checkbox, 2, 1)
        sequence_row.addWidget(self.sync_urls_button, 2, 2)
        sequence_layout.addLayout(sequence_row)
        layout.addWidget(sequence_box)

        launch_box = self._section_box("Launch Control / Publication Status", content)
        launch_layout = self._section_layout(launch_box)
        launch_row = QGridLayout()
        self.launch_status_label = QLabel("No launch-control audit yet.", self)
        self.launch_status_label.setWordWrap(True)
        self.refresh_status_button = QPushButton("Refresh Status", self)
        self.activation_dry_run_button = QPushButton("Activation Dry Run", self)
        self.activate_campaign_button = QPushButton("Activate Campaign", self)
        self.activate_campaign_button.setEnabled(False)
        self.resume_publication_button = QPushButton("Resume Publication", self)
        launch_row.addWidget(self.launch_status_label, 0, 0, 1, 4)
        launch_row.addWidget(self.refresh_status_button, 1, 0)
        launch_row.addWidget(self.activation_dry_run_button, 1, 1)
        launch_row.addWidget(self.activate_campaign_button, 1, 2)
        launch_row.addWidget(self.resume_publication_button, 1, 3)
        launch_layout.addLayout(launch_row)

        self.reconciliation_label = QLabel("Reconciliation: Not checked", self)
        self.reconciliation_label.setWordWrap(True)
        launch_layout.addWidget(self.reconciliation_label)
        layout.addWidget(launch_box)

        pilot_box = self._section_box("Pilot Launch Safety Harness", content)
        pilot_layout = self._section_layout(pilot_box)

        pilot_row = QGridLayout()
        pilot_row.setHorizontalSpacing(8)
        pilot_row.setVerticalSpacing(8)
        self.pilot_list = QComboBox(self)
        self.refresh_pilots_button = QPushButton("Refresh Pilots", self)
        self.create_pilot_button = QPushButton("Create Pilot", self)
        self.preflight_pilot_button = QPushButton("Pilot Preflight", self)
        self.dry_run_pilot_button = QPushButton("Pilot Activation Dry Run", self)
        self.activate_pilot_button = QPushButton("Activate Pilot", self)
        self.refresh_pilot_button = QPushButton("Refresh Pilot Status", self)
        self.pause_pilot_button = QPushButton("Pause Pilot Campaign", self)
        self.complete_pilot_button = QPushButton("Mark Pilot Review Complete", self)
        pilot_row.addWidget(QLabel("Pilot:", self), 0, 0)
        pilot_row.addWidget(self.pilot_list, 0, 1, 1, 3)
        pilot_row.addWidget(self.refresh_pilots_button, 0, 4)
        pilot_row.addWidget(self.create_pilot_button, 1, 1)
        pilot_row.addWidget(self.preflight_pilot_button, 1, 2)
        pilot_row.addWidget(self.dry_run_pilot_button, 1, 3)
        pilot_row.addWidget(self.activate_pilot_button, 1, 4)
        pilot_row.addWidget(self.refresh_pilot_button, 2, 1)
        pilot_row.addWidget(self.pause_pilot_button, 2, 2)
        pilot_row.addWidget(self.complete_pilot_button, 2, 3, 1, 2)
        pilot_layout.addLayout(pilot_row)

        self.pilot_status_label = QLabel("No pilot selected.", self)
        self.pilot_status_label.setWordWrap(True)
        pilot_layout.addWidget(self.pilot_status_label)

        self.pilot_summary = QPlainTextEdit(self)
        self.pilot_summary.setReadOnly(True)
        pilot_layout.addWidget(self.pilot_summary)

        self.pilot_recipient_list = QListWidget(self)
        pilot_layout.addWidget(self.pilot_recipient_list)

        self.pilot_metrics_label = QLabel("Pilot metrics: Not refreshed", self)
        self.pilot_health_label = QLabel("Health: Unknown", self)
        self.pilot_metrics_label.setWordWrap(True)
        self.pilot_health_label.setWordWrap(True)
        pilot_layout.addWidget(self.pilot_metrics_label)
        pilot_layout.addWidget(self.pilot_health_label)
        layout.addWidget(pilot_box)
        layout.addStretch(1)

    def _section_box(self, title: str, parent: QWidget) -> QGroupBox:
        box = QGroupBox(title, parent)
        box.setObjectName("cardFrame")
        return box

    def _section_layout(self, box: QGroupBox) -> QVBoxLayout:
        section = QVBoxLayout(box)
        section.setContentsMargins(12, 12, 12, 12)
        section.setSpacing(10)
        return section

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
        if hasattr(controller, "hosting_connection_changed"):
            controller.hosting_connection_changed.connect(self.set_hosting_connection_status)
        if hasattr(controller, "hosting_summary_changed"):
            controller.hosting_summary_changed.connect(self.set_hosting_summary)
        if hasattr(controller, "readiness_changed"):
            controller.readiness_changed.connect(self.set_readiness)
        if hasattr(controller, "url_sync_changed"):
            controller.url_sync_changed.connect(self.set_url_sync)
        if hasattr(controller, "reconciliation_changed"):
            controller.reconciliation_changed.connect(self.set_reconciliation)
        if hasattr(controller, "launch_readiness_changed"):
            controller.launch_readiness_changed.connect(self.set_launch_readiness)
        if hasattr(controller, "activation_result_changed"):
            controller.activation_result_changed.connect(self.set_activation_result)
        if hasattr(controller, "pilot_changed"):
            controller.pilot_changed.connect(self.set_pilot)
        if hasattr(controller, "pilot_list_changed"):
            controller.pilot_list_changed.connect(self.set_pilot_list)
        if hasattr(controller, "pilot_preflight_changed"):
            controller.pilot_preflight_changed.connect(self.show_pilot_preflight)
        if hasattr(controller, "pilot_activation_changed"):
            controller.pilot_activation_changed.connect(self.show_pilot_activation)
        if hasattr(controller, "pilot_pause_changed"):
            controller.pilot_pause_changed.connect(self.show_pilot_pause)
        self.test_connection_button.clicked.connect(self._on_test_connection)
        self.refresh_campaigns_button.clicked.connect(self._on_refresh_campaigns)
        self.publish_button.clicked.connect(self._on_publish)
        self.test_hosting_connection_button.clicked.connect(self._on_test_hosting_connection)
        self.hosting_dry_run_button.clicked.connect(self._on_hosting_dry_run)
        self.host_mockups_button.clicked.connect(self._on_host_mockups)
        self.refresh_readiness_button.clicked.connect(self._on_refresh_readiness)
        self.prepare_sequence_button.clicked.connect(self._on_prepare_sequence)
        self.sync_urls_button.clicked.connect(self._on_sync_urls)
        self.refresh_status_button.clicked.connect(self._on_refresh_status)
        self.activation_dry_run_button.clicked.connect(self._on_activation_dry_run)
        self.activate_campaign_button.clicked.connect(self._on_activate_campaign)
        self.resume_publication_button.clicked.connect(self._on_resume_publication)
        self.create_pilot_button.clicked.connect(self._on_create_pilot)
        self.preflight_pilot_button.clicked.connect(self._on_preflight_pilot)
        self.dry_run_pilot_button.clicked.connect(self._on_dry_run_pilot)
        self.activate_pilot_button.clicked.connect(self._on_activate_pilot)
        self.refresh_pilot_button.clicked.connect(self._on_refresh_pilot)
        self.pause_pilot_button.clicked.connect(self._on_pause_pilot)
        self.complete_pilot_button.clicked.connect(self._on_complete_pilot)
        self.pilot_recipient_list.itemSelectionChanged.connect(self._update_pilot_buttons)
        self.target_mode_combo.currentTextChanged.connect(self._sync_target_mode)
        self.campaign_combo.currentIndexChanged.connect(self._update_activation_button_state)
        self.live_checkbox.toggled.connect(self._update_activation_button_state)
        self._sync_target_mode(self.target_mode_combo.currentText())

    def set_summary(self, summary: object) -> None:
        self._handoff_directory = str(getattr(summary, "handoff_directory", "") or self._handoff_directory)
        if self._handoff_directory:
            candidate = os.path.dirname(self._handoff_directory)
            self._package_directory = candidate if os.path.isfile(os.path.join(candidate, "manifest.json")) else self._handoff_directory
        total = getattr(summary, "total_approved_rows", 0)
        if not total:
            self.summary_label.setText("No campaign package selected. Build an approved package from Campaign Review, or choose an existing package.")
            return
        self.summary_label.setText(
            f"Campaign package: {total} approved rows | "
            f"Ready: {getattr(summary, 'ready', 0)} | "
            f"Needs attention: {getattr(summary, 'blocked', 0) + getattr(summary, 'conflicts', 0)}"
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
        if self._handoff_directory:
            candidate = os.path.dirname(self._handoff_directory)
            self._package_directory = candidate if os.path.isfile(os.path.join(candidate, "manifest.json")) else self._handoff_directory

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
        if hasattr(controller, "refresh_pilots"):
            controller.refresh_pilots()

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

    # ------------------------------------------------------------------
    # Hosting (Sprint 5R)
    # ------------------------------------------------------------------
    def set_hosting_connection_status(self, result: object) -> None:
        status = str(getattr(result, "status", "") or "")
        self.hosting_status_label.setText(f"Hosting: {status}")
        self.show_status(str(getattr(result, "message", "") or ""))

    def set_hosting_summary(self, result: object) -> None:
        lines = [str(getattr(result, "message", "") or "")]
        lines.append(
            f"Hosted: {getattr(result, 'hosted', 0)} | Reused: {getattr(result, 'reused', 0)} | "
            f"Pending: {getattr(result, 'pending', 0)} | Failed: {getattr(result, 'failed', 0)} | Blocked: {getattr(result, 'blocked', 0)}"
        )
        self.hosting_summary_label.setText(" | ".join(lines))
        self.show_status("\n".join(lines))

    def _on_test_hosting_connection(self) -> None:
        if self._controller is not None and hasattr(self._controller, "test_hosting_connection"):
            self._controller.test_hosting_connection()

    def _on_hosting_dry_run(self) -> None:
        if self._controller is None:
            return
        if hasattr(self._controller, "hosting_dry_run"):
            self._controller.hosting_dry_run(self._package_directory, self._handoff_directory)

    def _on_host_mockups(self) -> None:
        if self._controller is None:
            return
        live = self.hosting_live_checkbox.isChecked()
        confirmed = True
        if live:
            confirmed = QMessageBox.question(self, "Confirm Hosting", "Upload approved mockups to the configured hosting provider?") == QMessageBox.StandardButton.Yes
        if hasattr(self._controller, "host_mockups"):
            self._controller.host_mockups(
                self._package_directory,
                self._handoff_directory,
                mode="LIVE" if live else "DRY_RUN",
                live_enabled=live,
                confirmed=confirmed,
            )

    # ------------------------------------------------------------------
    # Sequence readiness + URL sync (Sprint 5R)
    # ------------------------------------------------------------------
    def set_readiness(self, result: object) -> None:
        lines = [
            f"Campaign: {getattr(result, 'campaign_id', '')} | Status: {getattr(result, 'campaign_status', '')}",
            f"Sequence exists: {getattr(result, 'sequence_exists', False)}",
            f"bb_subject: {getattr(result, 'bb_subject_present', False)} | bb_body: {getattr(result, 'bb_body_present', False)} | bb_mockup_url: {getattr(result, 'bb_mockup_url_present', False)}",
            f"Sender accounts: {getattr(result, 'sender_account_count', 0)}",
        ]
        blockers = list(getattr(result, "blockers", ()) or ())
        if blockers:
            lines.append("Cannot continue: " + "; ".join(format_blocker(item) for item in blockers))
        ready = bool(getattr(result, "ready_for_manual_activation", False))
        lines.append("Ready for launch review" if ready else "Sequence readiness needs attention")
        self.readiness_label.setText(" | ".join(lines[:3]))
        self.show_status("\n".join(lines))

    def set_url_sync(self, result: object) -> None:
        lines = [str(getattr(result, "message", "") or "")]
        lines.append(
            f"Synced: {getattr(result, 'synced', 0)} | Skipped: {getattr(result, 'skipped', 0)} | "
            f"Failed: {getattr(result, 'failed', 0)} | Not syncable: {getattr(result, 'not_syncable', 0)}"
        )
        self.show_status("\n".join(lines))

    def set_reconciliation(self, result: object) -> None:
        text = (
            f"Smartlead status: {'Ready' if not getattr(result, 'reconciliation_required', False) else 'Needs attention'} | "
            f"Matched: {getattr(result, 'matched', 0)} | Local Only: {getattr(result, 'local_only', 0)} | "
            f"Remote Only: {getattr(result, 'remote_only', 0)} | Mismatch: {getattr(result, 'mismatched', 0)} | "
            f"Duplicate Remote: {getattr(result, 'duplicate_remote', 0)}"
        )
        self.reconciliation_label.setText(text)
        lines = [text]
        reasons = list(getattr(result, "reasons", ()) or ())
        warnings = list(getattr(result, "warnings", ()) or ())
        if reasons:
            lines.append("Details: " + "; ".join(format_blocker(reason) for reason in reasons))
        if warnings:
            lines.append("Warnings: " + "; ".join(format_status(warning) for warning in warnings))
        self.show_status("\n".join(lines))

    def set_launch_readiness(self, result: object) -> None:
        self._last_launch_readiness = result
        text = (
            f"Campaign: {getattr(result, 'campaign_name', '') or getattr(result, 'campaign_id', '')} | "
            f"Publication: {getattr(result, 'published_count', 0)} published / {getattr(result, 'failed_count', 0)} failed / {getattr(result, 'pending_count', 0)} pending | "
            f"Sequence: {'Ready' if getattr(result, 'sequence_ready', False) else 'Needs attention'} | "
            f"Assets Missing: {getattr(result, 'missing_asset_count', 0)} | Overall: {format_status(getattr(result, 'status', 'NOT_READY'))}"
        )
        self.launch_status_label.setText(text)
        lines = [text]
        reasons = list(getattr(result, "reasons", ()) or ())
        warnings = list(getattr(result, "warnings", ()) or ())
        if reasons:
            lines.append("Cannot continue: " + "; ".join(format_blocker(reason) for reason in reasons))
        if warnings:
            lines.append("Warnings: " + "; ".join(format_status(warning) for warning in warnings))
        self.show_status("\n".join(lines))
        self._update_activation_button_state()

    def set_activation_result(self, result: object) -> None:
        self._last_activation_result = result
        lines = [str(getattr(result, "message", "") or "")]
        lines.append(
            f"Remote Status: {getattr(result, 'resulting_remote_status', '') or getattr(result, 'prior_remote_status', '')} | "
            f"Readiness: {getattr(result, 'readiness_status', '')} | Result: {getattr(result, 'status', '')}"
        )
        receipt = getattr(result, "receipt", None)
        if receipt is not None:
            lines.append(f"Activated At: {getattr(receipt, 'completed_at', '')}")
        self.show_status("\n".join(lines))
        self._update_activation_button_state()

    def _on_refresh_readiness(self) -> None:
        if self._controller is None:
            return
        campaign_id = str(self.campaign_combo.currentData() or "")
        if campaign_id and hasattr(self._controller, "refresh_sequence_readiness"):
            self._controller.refresh_sequence_readiness(campaign_id)

    def _on_prepare_sequence(self) -> None:
        if self._controller is None:
            return
        campaign_id = str(self.campaign_combo.currentData() or "")
        if not campaign_id:
            return
        live = self.prepare_live_checkbox.isChecked()
        confirmed = True
        if live:
            confirmed = QMessageBox.question(self, "Confirm Sequence", "Prepare the BillboardAI draft sequence for this campaign? (No activation.)") == QMessageBox.StandardButton.Yes
        if hasattr(self._controller, "prepare_sequence"):
            self._controller.prepare_sequence(campaign_id, live_enabled=live, confirmed=confirmed)

    def _on_sync_urls(self) -> None:
        if self._controller is None:
            return
        source_package_id = self._package_id()
        campaign_id = str(self.campaign_combo.currentData() or "")
        if not source_package_id or not campaign_id:
            self.show_status("Sync requires an approved package and a target campaign.")
            return
        live = self.sync_live_checkbox.isChecked()
        confirmed = True
        if live:
            confirmed = QMessageBox.question(self, "Confirm URL Sync", "Update bb_mockup_url on existing Smartlead leads? (No activation.)") == QMessageBox.StandardButton.Yes
        if hasattr(self._controller, "sync_hosted_urls"):
            self._controller.sync_hosted_urls(
                source_package_id=source_package_id,
                campaign_id=campaign_id,
                mode="LIVE" if live else "DRY_RUN",
                live_enabled=live,
                confirmed=confirmed,
            )

    def _on_refresh_status(self) -> None:
        if self._controller is None:
            return
        source_package_id = self._package_id()
        campaign_id = str(self.campaign_combo.currentData() or "")
        if not source_package_id or not campaign_id:
            self.show_status("Status refresh requires an approved package and a target campaign.")
            return
        if hasattr(self._controller, "refresh_reconciliation"):
            self._controller.refresh_reconciliation(source_package_id=source_package_id, campaign_id=campaign_id)
        if hasattr(self._controller, "refresh_launch_readiness"):
            self._controller.refresh_launch_readiness(source_package_id=source_package_id, campaign_id=campaign_id)

    def _on_activation_dry_run(self) -> None:
        if self._controller is None:
            return
        source_package_id = self._package_id()
        campaign_id = str(self.campaign_combo.currentData() or "")
        if not source_package_id or not campaign_id:
            self.show_status("Activation preview requires an approved package and a target campaign.")
            return
        if hasattr(self._controller, "activation_preview"):
            self._controller.activation_preview(source_package_id=source_package_id, campaign_id=campaign_id)

    def _on_activate_campaign(self) -> None:
        if self._controller is None:
            return
        source_package_id = self._package_id()
        campaign_id = str(self.campaign_combo.currentData() or "")
        if not source_package_id or not campaign_id:
            self.show_status("Campaign activation requires an approved package and a target campaign.")
            return
        if not self.live_checkbox.isChecked():
            self.show_status("Enable live Smartlead writes before activating a campaign.")
            return
        if hasattr(self._controller, "activation_preview"):
            self._controller.activation_preview(source_package_id=source_package_id, campaign_id=campaign_id)
        box = QMessageBox(self)
        box.setWindowTitle("Confirm Campaign Activation")
        box.setText(self._build_activation_confirmation_message(campaign_id))
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        yes = box.button(QMessageBox.StandardButton.Yes)
        if yes is not None:
            yes.setText(self._activation_button_text())
        cancel = box.button(QMessageBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setText("Cancel")
        confirmed = box.exec() == int(QMessageBox.StandardButton.Yes)
        if hasattr(self._controller, "activate_campaign"):
            self._controller.activate_campaign(
                source_package_id=source_package_id,
                campaign_id=campaign_id,
                mode=SMARTLEAD_PUBLISH_MODE_LIVE,
                live_enabled=self.live_checkbox.isChecked(),
                confirmed=confirmed,
            )

    def _on_resume_publication(self) -> None:
        if self._controller is None:
            return
        target = self._publish_target()
        live = self.live_checkbox.isChecked()
        confirmed = True
        if live:
            confirmed = QMessageBox.question(self, "Confirm Resume", self._confirmation_message(target, SMARTLEAD_PUBLISH_MODE_LIVE)) == QMessageBox.StandardButton.Yes
        if hasattr(self._controller, "resume_publication"):
            self._controller.resume_publication(
                self._handoff_directory,
                target=target,
                mode=SMARTLEAD_PUBLISH_MODE_LIVE if live else SMARTLEAD_PUBLISH_MODE_DRY_RUN,
                live_enabled=live,
                confirmed=confirmed,
            )

    def _package_id(self) -> str:
        manifest_path = os.path.join(self._package_directory, "manifest.json") if self._package_directory else ""
        if manifest_path and os.path.isfile(manifest_path):
            import json

            try:
                with open(manifest_path, "r", encoding="utf-8") as handle:
                    return str(json.load(handle).get("package_id") or "")
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def _activation_button_text(self) -> str:
        prior = str(getattr(self._last_activation_result, "prior_remote_status", "") or "").upper()
        return "Resume Campaign" if prior == "PAUSED" else "Activate Campaign"

    def _build_activation_confirmation_message(self, campaign_id: str) -> str:
        readiness = self._last_launch_readiness
        campaign_name = self.campaign_combo.currentText().split(" (")[0].strip()
        remote_status = str(getattr(self._last_activation_result, "prior_remote_status", "") or "").upper() or "DRAFT / PAUSED"
        return "\n".join(
            [
                f"Campaign: {campaign_name}",
                f"Smartlead Campaign ID: {campaign_id}",
                f"Published Leads: {getattr(readiness, 'published_count', 0) if readiness is not None else 0}",
                f"Sequence: {'Ready' if getattr(readiness, 'sequence_ready', False) else 'Not Ready'}",
                f"Hosted Assets: {'Ready' if getattr(readiness, 'missing_asset_count', 0) == 0 else 'Not Ready'}",
                f"Sender Accounts: {self._sender_accounts_summary()}",
                f"Reconciliation: {'Matched' if readiness is not None and not getattr(readiness, 'reconciliation_required', False) else 'Attention Required'}",
                f"Remote Status: {remote_status}",
                "",
                "Warning:",
                "Smartlead may begin sending according to the campaign's configured schedule and settings.",
            ]
        )

    def _sender_accounts_summary(self) -> str:
        text = self.readiness_label.text()
        marker = "Sender accounts: "
        if marker in text:
            return text.split(marker, 1)[1].split(" |", 1)[0]
        return "Unknown"

    def _update_activation_button_state(self, *_args) -> None:
        campaign_selected = bool(str(self.campaign_combo.currentData() or ""))
        live_enabled = self.live_checkbox.isChecked()
        readiness_ready = str(getattr(self._last_launch_readiness, "status", "") or "") == "READY"
        remote_active = str(getattr(self._last_activation_result, "resulting_remote_status", "") or "").upper() in {"ACTIVE", "STARTED", "RUNNING", "SENDING"}
        self.activate_campaign_button.setText(self._activation_button_text())
        self.activate_campaign_button.setEnabled(campaign_selected and live_enabled and readiness_ready and not remote_active)

    def set_pilot_list(self, pilots: list[object]) -> None:
        self._pilot_runs = list(pilots or [])
        self._update_pilot_buttons()

    def set_pilot(self, pilot: object) -> None:
        definition = getattr(pilot, "definition", pilot)
        if definition is None:
            return
        self._current_pilot_id = str(getattr(definition, "pilot_id", "") or "")
        self.pilot_status_label.setText(
            f"Pilot: {getattr(definition, 'campaign_name', '')} | Status: {getattr(definition, 'status', '')} | Recipients: {len(getattr(definition, 'recipients', ())) }"
        )
        self._apply_pilot_recipients(getattr(definition, "recipients", ()))
        snapshot = getattr(pilot, "snapshot", None)
        if snapshot is not None:
            metrics = getattr(snapshot, "pilot_metrics", None)
            self.pilot_metrics_label.setText(
                f"Pilot metrics: sent={getattr(metrics, 'sent', 0)} | replies={getattr(metrics, 'replied', 0)} | bounces={getattr(metrics, 'bounced', 0)} | opened={getattr(metrics, 'opened', 0)} | clicked={getattr(metrics, 'clicked', 0)}"
            )
            self.pilot_health_label.setText(
                f"Health: {getattr(snapshot, 'health', '')} | Remote campaign: {getattr(snapshot, 'remote_campaign_status', '')} | Last refresh: {getattr(snapshot, 'last_checked_at', '')}"
            )
        self._update_pilot_buttons()

    def show_pilot_preflight(self, result: object) -> None:
        checks = getattr(result, "checks", ()) or ()
        text = "\n".join([f"[{'PASS' if item.passed else 'FAIL'}] {item.name} — {item.message}" for item in checks])
        self.detail.setPlainText(text or getattr(result, "message", ""))

    def show_pilot_activation(self, result: object) -> None:
        self.detail.setPlainText(getattr(result, "message", ""))

    def show_pilot_pause(self, result: object) -> None:
        self.detail.setPlainText(getattr(result, "message", ""))

    def _apply_pilot_recipients(self, recipients: object) -> None:
        selected_ids = {item.data(0) for item in self.pilot_recipient_list.selectedItems()}
        self.pilot_recipient_list.clear()
        for recipient in recipients or ():
            item = QListWidgetItem(f"{getattr(recipient, 'email', '')} ({getattr(recipient, 'prospect_id', '')})")
            item.setData(0, getattr(recipient, "prospect_id", ""))
            self.pilot_recipient_list.addItem(item)
            if item.data(0) in selected_ids:
                item.setSelected(True)

    def _selected_pilot_prospect_ids(self) -> list[str]:
        selected = [str(item.data(0) or "") for item in self.pilot_recipient_list.selectedItems()]
        if selected:
            return selected
        rows = [row for row in self._rows if str(row.get("status") or "").strip().upper() in {"READY", "WARNING"}]
        return [str(row.get("prospect_id") or "") for row in rows[:5] if str(row.get("prospect_id") or "").strip()]

    def _selected_pilot_emails(self) -> list[str]:
        selected = []
        selected_ids = set(self._selected_pilot_prospect_ids())
        for row in self._rows:
            if str(row.get("prospect_id") or "") in selected_ids:
                selected.append(str(row.get("email") or ""))
        return selected

    def _current_pilot_run(self):
        for run in self._pilot_runs:
            definition = getattr(run, "definition", None)
            if definition is not None and str(getattr(definition, "pilot_id", "") or "") == self._current_pilot_id:
                return run
        return None

    def _on_create_pilot(self) -> None:
        if self._controller is None:
            return
        campaign_id = str(self.campaign_combo.currentData() or "")
        campaign_name = self.campaign_combo.currentText().split(" (")[0].strip()
        if not campaign_id:
            self.show_status("Select a Smartlead campaign first.")
            return
        selected_ids = self._selected_pilot_prospect_ids()
        selected_emails = self._selected_pilot_emails()
        if hasattr(self._controller, "create_pilot"):
            self._controller.create_pilot(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=self._package_id(),
                source_handoff_path=self._handoff_directory,
                selected_prospect_ids=selected_ids,
                selected_emails=selected_emails,
            )

    def _on_preflight_pilot(self) -> None:
        if self._controller is None or not self._current_pilot_id:
            return
        if hasattr(self._controller, "preflight_pilot"):
            self._controller.preflight_pilot(self._current_pilot_id)

    def _on_dry_run_pilot(self) -> None:
        if self._controller is None or not self._current_pilot_id:
            return
        if hasattr(self._controller, "dry_run_pilot"):
            self._controller.dry_run_pilot(self._current_pilot_id)

    def _on_activate_pilot(self) -> None:
        if self._controller is None or not self._current_pilot_id:
            return
        run = self._current_pilot_run()
        definition = getattr(run, "definition", None)
        if definition is None:
            return
        campaign_name = getattr(definition, "campaign_name", "")
        recipient_count = len(getattr(definition, "recipients", ()))
        campaign_id = getattr(definition, "campaign_id", "")
        message = "\n".join(
            [
                "PILOT CAMPAIGN",
                "",
                f"Campaign:\n{campaign_name}",
                "",
                f"Recipients:\n{recipient_count}",
                "",
                f"Remote Campaign:\n{campaign_id}",
                "",
                "Sequence:\nReady",
                "",
                "Assets:\nReady",
                "",
                "Reconciliation:\nMatched",
                "",
                "WARNING:",
                "",
                "Activating this campaign may cause Smartlead to begin sending according to its configured campaign schedule and settings.",
                "",
                "Emergency control:",
                "Pause Campaign",
            ]
        )
        box = QMessageBox(self)
        box.setWindowTitle("Activate Pilot")
        box.setText(message)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        activate = box.addButton("Activate Pilot", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is activate and hasattr(self._controller, "activate_pilot"):
            self._controller.activate_pilot(self._current_pilot_id, confirmed=True)

    def _on_refresh_pilot(self) -> None:
        if self._controller is None or not self._current_pilot_id:
            return
        if hasattr(self._controller, "refresh_pilot_status"):
            self._controller.refresh_pilot_status(self._current_pilot_id)

    def _on_pause_pilot(self) -> None:
        if self._controller is None or not self._current_pilot_id:
            return
        run = self._current_pilot_run()
        definition = getattr(run, "definition", None)
        if definition is None:
            return
        campaign_name = getattr(definition, "campaign_name", "")
        box = QMessageBox(self)
        box.setWindowTitle("Pause Pilot Campaign")
        box.setText(f'Pause Smartlead campaign "{campaign_name}"?\n\nThis temporarily stops sending according to Smartlead campaign behavior.')
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        pause = box.addButton("Pause Campaign", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is pause and hasattr(self._controller, "pause_pilot"):
            self._controller.pause_pilot(self._current_pilot_id, confirmed=True)

    def _on_complete_pilot(self) -> None:
        if self._controller is None or not self._current_pilot_id:
            return
        if hasattr(self._controller, "mark_pilot_review_complete"):
            self._controller.mark_pilot_review_complete(self._current_pilot_id)

    def _update_pilot_buttons(self) -> None:
        has_pilot = bool(self._current_pilot_id)
        run = self._current_pilot_run()
        definition = getattr(run, "definition", None)
        status = str(getattr(definition, "status", "") or "")
        self.preflight_pilot_button.setEnabled(has_pilot)
        self.dry_run_pilot_button.setEnabled(has_pilot)
        self.activate_pilot_button.setEnabled(has_pilot and status == "READY")
        self.refresh_pilot_button.setEnabled(has_pilot)
        self.pause_pilot_button.setEnabled(has_pilot and status == "ACTIVE")
        self.complete_pilot_button.setEnabled(has_pilot and status in {"ACTIVE", "PAUSED", "ATTENTION_REQUIRED"})
