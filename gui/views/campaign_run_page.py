"""Sprint 5W Campaign Run workspace page.

A simple, responsive operator-facing workspace over the read-only
:class:`gui.controllers.campaign_run_controller.CampaignRunController`.

Top: run name, total prospects, progress summary, recommended next action,
and a "Continue Campaign" button (read-only navigation).
Main: a table of one row per prospect with derived stage columns.
Detail: blockers, selected prospect summary, and Open Prospect / Open Project /
Open Review / Open Smartlead actions. Primary actions NAVIGATE or invoke
EXISTING stage actions; the page itself reproduces no editors.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QHeaderView,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CampaignRunPage(QWidget):
    COL_COMPANY = 0
    COL_EMAIL = 1
    COL_RESEARCH = 2
    COL_OPPORTUNITY = 3
    COL_GENERATE = 4
    COL_OUTREACH = 5
    COL_REVIEW = 6
    COL_SMARTLEAD = 7
    COL_NEXT_ACTION = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._row_ids: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        heading = QLabel("Campaign Run", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.run_combo = QComboBox(self)
        self.run_combo.setEditable(False)
        self.run_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.run_combo.setPlaceholderText("Select a campaign run")
        self.run_combo.setMinimumContentsLength(18)
        self.run_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.run_combo.currentIndexChanged.connect(self._on_run_selected)
        top.addWidget(QLabel("Run:", self))
        top.addWidget(self.run_combo, 2)
        self.new_run_button = QPushButton("New Run…", self)
        self.new_run_button.clicked.connect(self._on_new_run)
        top.addWidget(self.new_run_button)
        self.add_prospects_button = QPushButton("Add Prospects…", self)
        self.add_prospects_button.clicked.connect(self._on_add_prospects)
        top.addWidget(self.add_prospects_button)
        layout.addLayout(top)

        self.summary_label = QLabel("No active campaign run.", self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("summaryLabel")
        layout.addWidget(self.summary_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.next_action_label = QLabel("", self)
        self.next_action_label.setWordWrap(True)
        action_row.addWidget(self.next_action_label, 3)
        self.continue_button = QPushButton("Continue Campaign", self)
        self.continue_button.setObjectName("primaryButton")
        self.continue_button.clicked.connect(self._on_continue)
        action_row.addWidget(self.continue_button)
        layout.addLayout(action_row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        layout.addWidget(self.splitter, 1)

        left = QWidget(self.splitter)
        left.setMinimumWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.table = QTableWidget(0, 9, left)
        self.table.setHorizontalHeaderLabels(
            ["Company", "Email", "Research", "Opportunity", "Generate",
             "Outreach", "Review", "Smartlead", "Next Action"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            "QTableWidget::item:selected { background-color: #7c5cfc; color: #ffffff; }"
            " QTableWidget::item:selected:active { background-color: #7c5cfc; color: #ffffff; }"
        )
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_COMPANY, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_EMAIL, QHeaderView.ResizeMode.Stretch)
        for column in (
            self.COL_RESEARCH,
            self.COL_OPPORTUNITY,
            self.COL_GENERATE,
            self.COL_OUTREACH,
            self.COL_REVIEW,
            self.COL_SMARTLEAD,
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_NEXT_ACTION, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(self.COL_NEXT_ACTION, 180)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        left_layout.addWidget(self.table)

        right = self._build_detail_pane(self.splitter)
        right.setMinimumWidth(260)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([760, 420])

    def _build_detail_pane(self, parent: QWidget) -> QWidget:
        right = QWidget(parent)
        outer = QVBoxLayout(right)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        scroll = QScrollArea(right)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content = QWidget(scroll)
        content.setMinimumHeight(0)
        scroll.setWidget(content)
        form = QFormLayout(content)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(6)

        self.detail_company = QLabel("", content)
        self.detail_prospect_id = QLabel("", content)
        self.detail_email = QLabel("", content)
        self.detail_website = QLabel("", content)
        self.detail_project_id = QLabel("", content)
        self.detail_job_id = QLabel("", content)
        self.detail_opportunity_id = QLabel("", content)
        self.detail_review_value = QLabel("", content)
        self.detail_technical = QLabel("", content)
        self.detail_next_action = QLabel("", content)
        for label in (self.detail_company, self.detail_prospect_id, self.detail_email,
                      self.detail_website, self.detail_project_id, self.detail_job_id,
                      self.detail_opportunity_id, self.detail_review_value,
                      self.detail_technical, self.detail_next_action):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Company:", self.detail_company)
        form.addRow("Prospect ID:", self.detail_prospect_id)
        form.addRow("Email:", self.detail_email)
        form.addRow("Website:", self.detail_website)
        form.addRow("Project ID:", self.detail_project_id)
        form.addRow("Generation Job:", self.detail_job_id)
        form.addRow("Opportunity ID:", self.detail_opportunity_id)
        form.addRow("Review:", self.detail_review_value)
        form.addRow("Technical:", self.detail_technical)
        form.addRow("Next Action:", self.detail_next_action)

        self.blockers_edit = QTextEdit(content)
        self.blockers_edit.setReadOnly(True)
        self.blockers_edit.setMinimumHeight(60)
        self.blockers_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        form.addRow("Blockers:", self.blockers_edit)
        outer.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.open_prospect_button = QPushButton("Open Prospect", right)
        self.open_prospect_button.clicked.connect(self._on_open_prospect)
        self.open_project_button = QPushButton("Open Project", right)
        self.open_project_button.clicked.connect(self._on_open_project)
        self.open_review_button = QPushButton("Open Review", right)
        self.open_review_button.clicked.connect(self._on_open_review)
        actions.addWidget(self.open_prospect_button)
        actions.addWidget(self.open_project_button)
        actions.addWidget(self.open_review_button)
        outer.addLayout(actions)

        smartlead_row = QHBoxLayout()
        smartlead_row.setSpacing(6)
        self.open_smartlead_button = QPushButton("Open Smartlead", right)
        self.open_smartlead_button.clicked.connect(self._on_open_smartlead)
        self.remove_button = QPushButton("Remove from Run", right)
        self.remove_button.clicked.connect(self._on_remove_prospect)
        smartlead_row.addWidget(self.open_smartlead_button)
        smartlead_row.addWidget(self.remove_button)
        smartlead_row.addStretch(1)
        outer.addLayout(smartlead_row)
        return right

    # ------------------------------------------------------------------
    # Controller wiring
    # ------------------------------------------------------------------
    def set_controller(self, controller) -> None:
        self._controller = controller
        if controller is None:
            return
        controller.runs_changed.connect(self._on_runs_changed)
        controller.run_opened.connect(self._on_run_opened)
        controller.rows_changed.connect(self.set_rows)
        controller.summary_changed.connect(self.set_summary)
        controller.status_message.connect(self.show_status)
        controller.error_message.connect(self.show_error)
        controller.runs_changed.emit(controller.list_runs())

    def show_status(self, message: str) -> None:
        if self._controller is not None:
            self._controller.status_message.emit(message)

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Campaign Run", str(message))

    # ------------------------------------------------------------------
    # View population (presentation-only formatting of derived state)
    # ------------------------------------------------------------------
    def _stage_label(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "—"
        return text.replace("_", " ").title()

    def set_runs(self, runs: list) -> None:
        current = self.run_combo.currentData()
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        self.run_combo.setPlaceholderText("Select a campaign run")
        active_id = self._controller.active_run_id() if self._controller else None
        for run in runs:
            label = str(run.get("name") or "Campaign Run")
            count = len(run.get("prospect_ids") or [])
            self.run_combo.addItem(f"{label} ({count})", run.get("id"))
        if self.run_combo.count() == 0:
            self.run_combo.addItem("No campaign runs yet", "")
            item = self.run_combo.model().item(0)
            if item is not None:
                item.setEnabled(False)
        # Prefer the active run; otherwise restore previous selection.
        target_index = -1
        if active_id:
            target_index = self.run_combo.findData(active_id)
        if target_index < 0 and current:
            target_index = self.run_combo.findData(current)
        if target_index >= 0:
            self.run_combo.setCurrentIndex(target_index)
        elif self.run_combo.count() > 0:
            self.run_combo.setCurrentIndex(0)
        self.run_combo.blockSignals(False)
        selected_run_id = str(self.run_combo.currentData() or "")
        if (
            self._controller is not None
            and selected_run_id
            and selected_run_id != self._controller.active_run_id()
        ):
            self._controller.open_run(selected_run_id)
        self._update_action_state()

    def set_rows(self, rows: list) -> None:
        selected_id = ""
        if self._controller is not None and hasattr(self._controller, "selected_prospect_id"):
            selected_id = str(self._controller.selected_prospect_id() or "")
        self.table.setRowCount(0)
        self._row_ids = []
        for row in rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            prospect_id = str(row.get("prospect_id") or "")
            self._row_ids.append(prospect_id)
            self.table.setItem(row_index, self.COL_COMPANY, QTableWidgetItem(str(row.get("company_name") or "")))
            self.table.setItem(row_index, self.COL_EMAIL, QTableWidgetItem(str(row.get("email") or "")))
            self.table.setItem(row_index, self.COL_RESEARCH, QTableWidgetItem(self._stage_label(row.get("research_status"))))
            self.table.setItem(row_index, self.COL_OPPORTUNITY, QTableWidgetItem(self._stage_label(row.get("opportunity_status"))))
            self.table.setItem(row_index, self.COL_GENERATE, QTableWidgetItem(self._stage_label(row.get("generation_status"))))
            self.table.setItem(row_index, self.COL_OUTREACH, QTableWidgetItem(self._stage_label(row.get("outreach_status"))))
            self.table.setItem(row_index, self.COL_REVIEW, QTableWidgetItem(self._stage_label(row.get("review_status"))))
            self.table.setItem(row_index, self.COL_SMARTLEAD, QTableWidgetItem(self._stage_label(row.get("smartlead_status"))))
            self.table.setItem(row_index, self.COL_NEXT_ACTION, QTableWidgetItem(str(row.get("next_action") or "")))
        self._sync_selection(selected_id)
        self._update_action_state()

    def clear_detail(self) -> None:
        self._populate_detail("")

    def set_summary(self, summary: dict) -> None:
        if not summary:
            self.summary_label.setText("No active campaign run.")
            self.next_action_label.setText("")
            self._update_action_state()
            return
        parts = [
            f"Total: {summary.get('total_prospects', 0)}",
            f"Research: {summary.get('research_complete', 0)}",
            f"Generated: {summary.get('generated', 0)}",
            f"Approved: {summary.get('approved', 0)}",
            f"Packageable: {summary.get('packageable', 0)}",
            f"Smartlead ready: {summary.get('smartlead_ready', 0)}",
            f"Needs attention: {summary.get('needs_attention', 0)}",
            f"Ready: {summary.get('ready', 0)}",
        ]
        state = str(summary.get("overall_state") or "").replace("_", " ").title()
        self.summary_label.setText(f"{state or 'In Progress'} — " + " • ".join(parts))
        action = str(summary.get("recommended_next_action") or "")
        self.next_action_label.setText(f"Recommended next action: {action}" if action else "")
        self._update_action_state()

    def current_prospect_id(self) -> str:
        row = self.table.currentRow()
        if 0 <= row < len(self._row_ids):
            return self._row_ids[row]
        return ""

    def _update_action_state(self) -> None:
        has_controller = self._controller is not None
        has_active = bool(self._controller and self._controller.active_run_id())
        has_selection = bool(self.current_prospect_id())
        self.continue_button.setEnabled(has_controller and has_active)
        self.add_prospects_button.setEnabled(has_controller and has_active)
        self.open_prospect_button.setEnabled(has_controller and has_selection)
        self.open_project_button.setEnabled(has_controller and has_selection)
        self.open_review_button.setEnabled(has_controller and has_active)
        self.open_smartlead_button.setEnabled(has_controller and has_active)
        self.remove_button.setEnabled(has_controller and has_selection)

    # ------------------------------------------------------------------
    # Event handlers (navigation / existing-action invocation only)
    # ------------------------------------------------------------------
    def _on_runs_changed(self, runs: object) -> None:
        self.set_runs(list(runs or []))

    def _on_run_opened(self, run: object) -> None:
        if self._controller is None:
            return
        self.set_runs(self._controller.list_runs())

    def _sync_selection(self, selected_id: str) -> None:
        target_index = -1
        if selected_id:
            for row_index, prospect_id in enumerate(self._row_ids):
                if prospect_id == selected_id:
                    target_index = row_index
                    break
        if target_index < 0 and self._row_ids:
            target_index = 0
        self.table.blockSignals(True)
        if target_index >= 0:
            scrollbar = self.table.horizontalScrollBar()
            previous_scroll = scrollbar.value() if scrollbar is not None else 0
            self.table.selectRow(target_index)
            self.table.setCurrentCell(target_index, self.COL_COMPANY)
            if scrollbar is not None:
                if target_index == 0:
                    scrollbar.setValue(scrollbar.minimum())
                else:
                    scrollbar.setValue(previous_scroll)
        else:
            self.table.clearSelection()
            self.clear_detail()
        self.table.blockSignals(False)
        if target_index >= 0:
            self._on_row_selected()

    def _on_run_selected(self, _index: int) -> None:
        if self._controller is None:
            return
        run_id = str(self.run_combo.currentData() or "")
        if run_id and run_id != self._controller.active_run_id():
            self._controller.open_run(run_id)

    def _on_new_run(self) -> None:
        if self._controller is None:
            return
        name, ok = QInputDialog.getText(self, "New Campaign Run", "Run name:")
        if not ok or not name.strip():
            return
        selected = self._pick_prospects(exclude=set())
        self._controller.create_run(name.strip(), selected, source="manual")

    def _on_add_prospects(self) -> None:
        if self._controller is None:
            return
        existing = set(self._controller.active_prospect_ids())
        selected = self._pick_prospects(exclude=existing)
        if selected:
            self._controller.add_prospects(selected)

    def _pick_prospects(self, *, exclude: set[str]) -> list[str]:
        """Modal multi-select picker over the canonical prospect store.

        Reuses stable prospect IDs only; creates no new selection store.
        """
        if self._controller is None:
            return []
        try:
            prospects = self._controller.service.prospect_store.list()
        except Exception:
            prospects = []
        if not prospects:
            self.show_error("No prospects are available yet. Import or add prospects first.")
            return []
        dialog = self._make_prospect_picker_dialog(prospects, exclude)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return []
        selected: list[str] = []
        for index in range(dialog.list_widget.count()):
            item = dialog.list_widget.item(index)
            if item.checkState() == Qt.CheckState.Checked and item.data(0x0100) not in exclude:
                selected.append(str(item.data(0x0100)))
        return selected

    def _make_prospect_picker_dialog(self, prospects, exclude: set[str]):
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QListWidget,
            QListWidgetItem,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Prospects for Campaign Run")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        list_widget = QListWidget(dialog)
        list_widget.setMinimumHeight(260)
        for prospect in prospects:
            pid = str(getattr(prospect, "prospect_id", "") or "")
            if not pid or pid in exclude:
                continue
            company = str(getattr(prospect, "company_name", "") or "")
            email = str(getattr(prospect, "email", "") or "")
            label = f"{company or '(no company)'} — {email or '(no email)'}"
            item = QListWidgetItem(label)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(0x0100, pid)
            list_widget.addItem(item)
        dialog.list_widget = list_widget
        layout.addWidget(list_widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog



    def _on_row_selected(self) -> None:
        prospect_id = self.current_prospect_id()
        if self._controller is not None and prospect_id:
            self._controller.select(prospect_id)
        self._populate_detail(prospect_id)
        self._update_action_state()

    def _populate_detail(self, prospect_id: str) -> None:
        if not prospect_id or self._controller is None:
            for label in (self.detail_company, self.detail_prospect_id, self.detail_email,
                          self.detail_website, self.detail_project_id, self.detail_job_id,
                          self.detail_opportunity_id, self.detail_review_value,
                          self.detail_technical, self.detail_next_action):
                label.setText("—")
            self.blockers_edit.clear()
            return
        detail = self._controller.detail_for(prospect_id)
        self.detail_company.setText(str(detail.get("company_name") or "—"))
        self.detail_prospect_id.setText(str(detail.get("prospect_id") or "—"))
        self.detail_email.setText(str(detail.get("email") or "—"))
        self.detail_website.setText(str(detail.get("website") or "—"))
        self.detail_project_id.setText(str(detail.get("project_id") or "—"))
        self.detail_job_id.setText(str(detail.get("generation_job_id") or "—"))
        self.detail_opportunity_id.setText(str(detail.get("opportunity_id") or "—"))
        self.detail_review_value.setText(str(detail.get("review_status_value") or "—"))
        self.detail_technical.setText(str(detail.get("technical_status") or "—"))
        self.detail_next_action.setText(str(detail.get("next_action") or "—"))
        blockers = list(detail.get("blockers") or [])
        self.blockers_edit.setPlainText("\n".join(blockers) if blockers else "No blockers.")

    def _on_continue(self) -> None:
        if self._controller is not None:
            self._controller.continue_campaign()

    def _on_open_prospect(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.open_prospect(prospect_id)

    def _on_open_project(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.open_project(prospect_id)

    def _on_open_review(self) -> None:
        if self._controller is not None:
            self._controller.open_review()

    def _on_open_smartlead(self) -> None:
        if self._controller is not None:
            self._controller.open_smartlead()

    def _on_remove_prospect(self) -> None:
        prospect_id = self.current_prospect_id()
        if not prospect_id or self._controller is None:
            return
        confirm = QMessageBox.question(
            self, "Remove from Run",
            f"Remove this prospect from the campaign run?\n"
            f"Canonical prospect data is not deleted.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._controller.remove_prospect(prospect_id)



