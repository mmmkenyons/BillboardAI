"""Minimal Smartlead preflight workspace."""

from __future__ import annotations

import os

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
        self._package_directory: str = ""

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

        # ------------------------------------------------------------------
        # Hosted Mockups (Sprint 5R)
        # ------------------------------------------------------------------
        hosting_title = QLabel("Hosted Mockups", self)
        hosting_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(hosting_title)

        hosting_row = QHBoxLayout()
        self.hosting_status_label = QLabel("Hosting: Not configured", self)
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
        layout.addLayout(hosting_row)
        self.hosting_summary_label = QLabel("No hosting run yet.", self)
        layout.addWidget(self.hosting_summary_label)

        # ------------------------------------------------------------------
        # Sequence Readiness (Sprint 5R)
        # ------------------------------------------------------------------
        sequence_title = QLabel("Sequence Readiness", self)
        sequence_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(sequence_title)

        sequence_row = QHBoxLayout()
        self.readiness_label = QLabel("No readiness audit yet.", self)
        self.refresh_readiness_button = QPushButton("Refresh Readiness", self)
        self.prepare_live_checkbox = QCheckBox("Enable live sequence write", self)
        self.prepare_live_checkbox.setChecked(False)
        self.prepare_sequence_button = QPushButton("Prepare Sequence", self)
        self.sync_live_checkbox = QCheckBox("Sync URLs live", self)
        self.sync_live_checkbox.setChecked(False)
        self.sync_urls_button = QPushButton("Sync Hosted URLs to Leads", self)
        sequence_row.addWidget(self.readiness_label)
        sequence_row.addStretch(1)
        sequence_row.addWidget(self.refresh_readiness_button)
        sequence_row.addWidget(self.prepare_live_checkbox)
        sequence_row.addWidget(self.prepare_sequence_button)
        sequence_row.addWidget(self.sync_live_checkbox)
        sequence_row.addWidget(self.sync_urls_button)
        layout.addLayout(sequence_row)

        # ------------------------------------------------------------------
        # Launch Control / Publication Status (Sprint 5S)
        # ------------------------------------------------------------------
        launch_title = QLabel("Launch Control / Publication Status", self)
        launch_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(launch_title)

        launch_row = QHBoxLayout()
        self.launch_status_label = QLabel("No launch-control audit yet.", self)
        self.refresh_status_button = QPushButton("Refresh Status", self)
        self.resume_publication_button = QPushButton("Resume Publication", self)
        launch_row.addWidget(self.launch_status_label)
        launch_row.addStretch(1)
        launch_row.addWidget(self.refresh_status_button)
        launch_row.addWidget(self.resume_publication_button)
        layout.addLayout(launch_row)

        self.reconciliation_label = QLabel("Reconciliation: Not checked", self)
        layout.addWidget(self.reconciliation_label)

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
        self.resume_publication_button.clicked.connect(self._on_resume_publication)
        self.target_mode_combo.currentTextChanged.connect(self._sync_target_mode)
        self._sync_target_mode(self.target_mode_combo.currentText())

    def set_summary(self, summary: object) -> None:
        self._handoff_directory = str(getattr(summary, "handoff_directory", "") or self._handoff_directory)
        if self._handoff_directory:
            candidate = os.path.dirname(self._handoff_directory)
            self._package_directory = candidate if os.path.isfile(os.path.join(candidate, "manifest.json")) else self._handoff_directory
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
            lines.append("Blockers: " + "; ".join(blockers))
        ready = bool(getattr(result, "ready_for_manual_activation", False))
        lines.append("READY FOR MANUAL ACTIVATION" if ready else "NOT READY (see blockers)")
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
            f"Reconciliation: {'Matched' if not getattr(result, 'reconciliation_required', False) else 'Attention Required'} | "
            f"Matched: {getattr(result, 'matched', 0)} | Local Only: {getattr(result, 'local_only', 0)} | "
            f"Remote Only: {getattr(result, 'remote_only', 0)} | Mismatch: {getattr(result, 'mismatched', 0)} | "
            f"Duplicate Remote: {getattr(result, 'duplicate_remote', 0)}"
        )
        self.reconciliation_label.setText(text)
        lines = [text]
        reasons = list(getattr(result, "reasons", ()) or ())
        warnings = list(getattr(result, "warnings", ()) or ())
        if reasons:
            lines.append("Reasons: " + "; ".join(reasons))
        if warnings:
            lines.append("Warnings: " + "; ".join(warnings))
        self.show_status("\n".join(lines))

    def set_launch_readiness(self, result: object) -> None:
        text = (
            f"Campaign: {getattr(result, 'campaign_name', '') or getattr(result, 'campaign_id', '')} | "
            f"Publication: {getattr(result, 'published_count', 0)} published / {getattr(result, 'failed_count', 0)} failed / {getattr(result, 'pending_count', 0)} pending | "
            f"Sequence: {'Ready' if getattr(result, 'sequence_ready', False) else 'Not Ready'} | "
            f"Assets Missing: {getattr(result, 'missing_asset_count', 0)} | Overall: {getattr(result, 'status', 'NOT_READY')}"
        )
        self.launch_status_label.setText(text)
        lines = [text]
        reasons = list(getattr(result, "reasons", ()) or ())
        warnings = list(getattr(result, "warnings", ()) or ())
        if reasons:
            lines.append("Reasons: " + "; ".join(reasons))
        if warnings:
            lines.append("Warnings: " + "; ".join(warnings))
        self.show_status("\n".join(lines))

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
